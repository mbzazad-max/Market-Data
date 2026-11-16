"""Check that every dashboard shows what Market-Data holds.

usage (GitHub Actions, workflow "Check dashboards"): GH_TOKEN=<token A> python check_dashboards.py [--rebuild]
       (locally, any token that can read the dashboard repos works)

For every dashboard in dashboards.json:
  1. Data: each series and reading the dashboard was built from (its public/freshness.json on main) against
     Market-Data's manifest.json: same last closed candle, same row count, same reading time.
       OK      the dashboard was built from the newest candle Market-Data has
       BEHIND  Market-Data has newer candles than the dashboard was built from
       AHEAD   the dashboard has a newer candle than Market-Data (should never happen)
       MISSING the series is no longer in Market-Data
     A tab or source the dashboard kept from an older build (it failed) is listed too.
  2. Build: the dashboard's latest build run (running, success, failure).
  3. Live site: the freshness.json the visitor gets (site in dashboards.json) against the repo's. "behind login"
     means the page is owner-only, so it could not be read from here.
  4. Upload age: how many candles behind "now" each used Binance/TradingView series is (your upload or the daily load).
  5. Due candles: Binance 1D within 3 h of the 11:00 Sydney close, Binance 4H at most 1 behind, TradingView candles
     closed before the daily 11:30 load (metals: weekend closure allowed), and any upload that held a closed candle
     the importer did not take. Readings (CoinGlass, CoinMarketCap, calendar) not loaded by today's 11:30 tasks.
With --rebuild, every dashboard that is BEHIND, failed, or not deployed is asked to rebuild (exit 3).
Writes a report to $GITHUB_STEP_SUMMARY (and prints it). Exit 1 when something needs attention.
"""
import json, os, sys, time, urllib.request, urllib.error
from mdlib import ROOT, series_registry

TOKEN = os.environ.get('GH_TOKEN', '')
REBUILD = '--rebuild' in sys.argv
NOW = float(os.environ.get('CHECK_NOW') or time.time())  # CHECK_NOW: test the rules at another time


def api(path, raw=False, method='GET', body=None):
    req = urllib.request.Request('https://api.github.com/' + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': 'Bearer ' + TOKEN, 'X-GitHub-Api-Version': '2022-11-28',
                                          'Accept': 'application/vnd.github.raw' if raw else 'application/vnd.github+json',
                                          'User-Agent': 'market-data-check'})
    with urllib.request.urlopen(req, timeout=30) as r:
        b = r.read()
        return json.loads(b) if b else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


def live(site):
    try:
        op = urllib.request.build_opener(NoRedirect)
        with op.open(urllib.request.Request(site.rstrip('/') + '/freshness.json?check=' + str(int(NOW)),
                                            headers={'User-Agent': 'market-data-check', 'Cache-Control': 'no-cache'}), timeout=30) as r:
            return 'ok', json.loads(r.read())
    except urllib.error.HTTPError as e:
        return ('login' if e.code in (301, 302, 303, 307, 401, 403) else 'error HTTP %d' % e.code), None
    except Exception as e:
        return 'error ' + str(e)[:80], None


def t2s(t):
    return time.strftime('%d %b %H:%M UTC', time.gmtime(t)) if t else '-'


man = json.loads((ROOT / 'manifest.json').read_text())
S, SNAP = man['series'], man.get('snapshots', {})
dash = json.loads((ROOT / 'dashboards.json').read_text())['dashboards']
lines = ['# Dashboards vs Market-Data', '', 'Checked ' + t2s(NOW) + '. Market-Data manifest generated ' + str(man.get('generated_at', '-')) + '.', '']
if man.get('errors_last_import'):
    lines += ['**Market-Data last import had errors:** ' + '; '.join(man['errors_last_import']), '']
problems, to_rebuild, ages = [], [], {}

for d in dash:
    repo, wf = d['repo'], d['workflow']
    name = repo.split('/')[1]
    lines += ['## ' + name, '']
    try:
        F = api('repos/%s/contents/public/freshness.json' % repo, raw=True)
    except Exception as e:
        lines += ['Could not read its freshness.json: ' + str(e), '']
        problems.append(name + ': freshness.json unreadable'); continue
    bad = []
    rows = ['| Series | Market-Data last candle | Dashboard built from | Rows MD / dash | Result |', '|---|---|---|---|---|']
    for s in F.get('series', []):
        sid = s.get('series') or s['id']
        built = s.get('built_from', s.get('last_open'))
        m = S.get(sid)
        label = (s.get('title') + ' · ' if s.get('title') else '') + sid
        if not m:
            res = 'MISSING'
        else:
            res = 'OK' if built == m['last_open'] else ('BEHIND' if (built or 0) < m['last_open'] else 'AHEAD')
            if res == 'OK' and s.get('rows') and s['rows'] != m['rows']: res = 'ROWS DIFFER'
            ages[sid] = m
        if res != 'OK': bad.append(label + ' ' + res)
        rows.append('| %s | %s | %s | %s / %s | %s |' % (label, t2s(m['last_open']) if m else '-', t2s(built), m['rows'] if m else '-', s.get('rows', '-'),
                                                          res if res == 'OK' else '**' + res + '**'))
    for r in F.get('readings', []):
        m = SNAP.get(r['id'])
        res = 'MISSING' if not m else 'OK' if r.get('fetched_at') == m['fetched_at'] else ('BEHIND' if (r.get('fetched_at') or 0) < m['fetched_at'] else 'AHEAD')
        if res != 'OK': bad.append(r['id'] + ' ' + res)
        rows.append('| %s (reading) | %s | %s | - | %s |' % (r['id'], t2s(m['fetched_at']) if m else '-', t2s(r.get('fetched_at')), res if res == 'OK' else '**' + res + '**'))
    for k in F.get('kept', []):
        bad.append('kept last good: %s (%s)' % (k.get('id'), k.get('why', '')))
    try:
        run = (api('repos/%s/actions/workflows/%s/runs?per_page=1' % (repo, wf)) or {}).get('workflow_runs', [])
        run = run[0] if run else None
    except Exception as e:
        run = None; lines.append('Could not read its build runs: ' + str(e))
    running = bool(run and run['status'] != 'completed')
    build_txt = ('none yet' if not run else ('running since ' + run['run_started_at'] if running else
                 '%s at %s (%s)' % (run['conclusion'], run['updated_at'], run['event'])))
    if run and not running and run['conclusion'] not in ('success', 'skipped'):
        bad.append('last build ' + str(run['conclusion']))
    site, lv = d.get('site'), None
    if site:
        st, L = live(site)
        if st == 'ok':
            lv = 'live page = repo (built ' + str(L.get('generated')) + ')' if L.get('generated') == F.get('generated') else \
                 '**live page is older than the repo** (live built %s, repo %s): deploy pending or failed' % (L.get('generated'), F.get('generated'))
            if L.get('generated') != F.get('generated'): bad.append('live page not updated')
        elif st == 'login':
            lv = 'behind login (owner-only), not checked from here'
        else:
            lv = 'could not open: ' + st; bad.append('live page ' + st)
    n = len(rows) - 2
    lines += ['Built ' + str(F.get('generated')) + ' · ' + str(F.get('last_result', '')), '',
              'Latest build: ' + build_txt + (' · Live: ' + lv if lv else ''), '',
              ('**Not OK:** ' + '; '.join(bad)) if bad else 'All %d inputs match Market-Data.' % n, '',
              '<details><summary>All %d inputs</summary>' % n, ''] + rows + ['', '</details>', '']
    if bad and running:
        lines += ['A build is running now; re-check in 2 minutes before acting on the items above.', '']
    if bad:
        problems.append(name + ': ' + '; '.join(bad))
        if not running: to_rebuild.append((repo, wf, name))

age_rows, late = [], []
DAY = 86400


def expected_close(sid, m):
    """Newest candle close this series should hold by now, or None when no rule applies."""
    P = m['period_s']
    newest = (int(NOW) // P) * P  # close of the newest candle that has closed on the exchange
    src, sym = sid.split('/')[0], sid.split('/')[1]
    if src == 'tv':
        # TradingView loads once a day at 11:30 Sydney (~00:30 UTC): only candles closed before that load are due.
        load = (int(NOW) // DAY) * DAY + 1800
        if NOW < load + 1800: load -= DAY
        due = (load // P) * P
        if sym.startswith('TVC_'):
            # metals: no trading from Friday ~22:00 UTC to Sunday ~23:00 UTC
            fri = load - ((time.gmtime(load).tm_wday - 4) % 7) * DAY  # last Friday 00:30 UTC
            if (fri // DAY) * DAY + 20 * 3600 <= m['last_close'] and NOW < (fri // DAY) * DAY + 3 * DAY + 3 * 3600:
                return m['last_close']
        return due
    if src == 'binance' and m['tf'] == '1D':
        return newest if NOW >= newest + 3 * 3600 else newest - P  # daily upload due within 3 h of the 11:00 Sydney close
    return newest - P  # Binance 4H: one candle of slack (the laptop uploads a few times a day)


FROZEN = {k for k, v in series_registry().items() if v.get('frozen')}  # stored history only, never loaded again
for sid, m in sorted(ages.items()):
    if sid in FROZEN:
        age_rows.append('| %s | %s | - | %s | stored history (frozen) |' % (sid, t2s(m['last_close']), t2s(m.get('fetched_at'))))
        continue
    behind = max(0, int((NOW - m['last_close']) // m['period_s']))
    why = ''
    nxt = m['last_close'] + m['period_s']
    # Daily candles only: a 1D candle left out because the file was saved inside the 5-min margin stays missing for a
    # day unless it is uploaded again. A 4H candle left out the same way arrives with the next upload, so 4H follows
    # the normal rule below (one candle of slack) and is reported only once it is really overdue.
    if m['tf'] == '1D' and m.get('checked_at', 0) >= nxt and m.get('forming_dropped_last_import'):
        why = 'the last upload already had the next candle but it was not imported (saved inside the 5-min margin and not confirmed by 4H)'
    else:
        due = expected_close(sid, m)
        if due is not None and m['last_close'] < due:
            why = '%d candle(s) due but not loaded' % ((due - m['last_close']) // m['period_s'])
    if why: late.append('%s: %s' % (sid, why))
    age_rows.append('| %s | %s | %s | %s | %s |' % (sid, t2s(m['last_close']), behind, t2s(m.get('fetched_at')), '**' + why + '**' if why else 'OK'))
lines += ['## Upload age (Market-Data vs now)', '', ('**Not loaded on time:** ' + '; '.join(late)) if late else 'Every used series has every candle that is due.', '',
          '<details><summary>All %d series</summary>' % len(age_rows), '', '| Series | Last closed candle | Candles behind now | File saved | Due? |', '|---|---|---|---|---|'] + age_rows + ['', '</details>']
lines += ['', 'Due = Binance 1D within 3 h of the 11:00 Sydney close; Binance 4H at most 1 candle behind; TradingView candles that closed before the daily 11:30 load (metals: weekend closure allowed).', '']
if late:
    problems.append('Market-Data: ' + '; '.join(late))

stale_reads = []
for sid, m in sorted(SNAP.items()):
    load = (int(NOW) // DAY) * DAY + 1800  # the daily 11:30 Sydney tasks (~00:30 UTC); allow them 1 h
    if NOW < load + 3600: load -= DAY
    if not m.get('fetched_at') or m['fetched_at'] < load - 3600:
        stale_reads.append('%s (%s h old, not loaded by today\'s 11:30 task)' % (sid, int((NOW - m['fetched_at']) // 3600) if m.get('fetched_at') else '?'))
if stale_reads:
    lines += ['**Readings not loaded today:** ' + ', '.join(stale_reads), '']
    problems.append('Readings: ' + ', '.join(stale_reads))

if REBUILD and to_rebuild:
    lines += ['## Rebuild requested', '']
    for repo, wf, name in to_rebuild:
        try:
            api('repos/%s/actions/workflows/%s/dispatches' % (repo, wf), method='POST', body={'ref': 'main', 'inputs': {'reason': 'Check dashboards', 'force': 'true'}})
            lines.append('- ' + name + ': rebuild started (forced). Run the check again in about 2 minutes.')
        except Exception as e:
            lines.append('- ' + name + ': could not start a rebuild: ' + str(e))
    lines.append('')

lines.insert(4, ('**All dashboards match Market-Data.**' if not problems else '**Needs attention:**\n' + '\n'.join('- ' + p for p in problems)) + '\n')
out = '\n'.join(lines)
print(out)
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f: f.write(out + '\n')
started = REBUILD and bool(to_rebuild)
# exit 3 = rebuilds were started (the scheduled check waits and checks again); 1 = needs attention; 0 = all good
sys.exit(3 if started else 1 if problems else 0)

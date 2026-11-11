# Saves your GitHub token encrypted for your Windows user (DPAPI). The token is never shown or written in plain text.
$ErrorActionPreference = 'Stop'
$secure = Read-Host 'Paste the market-data upload token, then press Enter (input is hidden)' -AsSecureString
if ($secure.Length -lt 20) { throw 'That does not look like a token.' }
$enc = ConvertFrom-SecureString -SecureString $secure
Set-Content -LiteralPath (Join-Path $PSScriptRoot 'github_token.dpapi') -Value $enc -Encoding ASCII
Write-Host 'Saved. You can now run UPLOAD.bat.'

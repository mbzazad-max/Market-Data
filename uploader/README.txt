MARKET DATA UPLOADER (laptop -> GitHub market-data)
===================================================
Sends new Binance 4H and 1D candles from your SPOT folder to GitHub in ONE commit, as small CSV text
files (not Excel), so the repo stays light. Your Excel files and your old uploader are not changed.

ONE-TIME SETUP
1. Copy this "uploader" folder somewhere permanent on your laptop (not inside the SPOT folder).
2. Check config.json: "spot_folder" must be your local SPOT folder (the one with LTF and HTF inside).
3. Install the Excel reader once:  pip install openpyxl
4. Make a GitHub token for this uploader only:
   GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens > Generate new token
   Repository access: Only select repositories > market-data
   Permissions > Repository permissions > Contents: Read and write.  Nothing else.
5. Double-click SETUP_TOKEN.bat and paste the token. It is saved encrypted for your Windows user only.
   Never paste the token into any file, chat or README.

EVERY DAY
After your Binance download has finished, double-click UPLOAD.bat.
It uploads only candles GitHub does not have yet. "Nothing new to upload" means GitHub is already current.

If the token expires, make a new one and run SETUP_TOKEN.bat again.

============================================================
 TECHNO COMMUNICATIONS - COMPLIANCE DATA WEBSITE
============================================================

WHAT IT DOES
------------
Pick a single market (or "All Markets"), choose a date range,
click "Get Compliance Data", and download the CSV. Same pull +
transpose logic as your Bulk Schedule Importer, trimmed to just
those two steps.


FILES
-----
    web_app.py            <- the web server
    compliance_core.py    <- pull + CSV engine
    templates/index.html  <- the page
    static/logo.png       <- logo
    requirements.txt
    run_website.bat       <- local launcher (Windows)
    Procfile              <- how the cloud host starts the app
    render.yaml           <- optional one-click Render blueprint
    .gitignore            <- keeps credentials.json OUT of git
    .python-version       <- pins Python 3.12 on the host


CREDENTIALS (the Google key)
----------------------------
The app looks for the service-account key in this order:
    1. GOOGLE_CREDENTIALS_JSON  (env var holding the whole JSON)
    2. /etc/secrets/credentials.json   (Render "Secret File")
    3. ./credentials.json              (local, next to web_app.py)

NEVER commit credentials.json to GitHub. .gitignore already
blocks it.


============================================================
 A) RUN LOCALLY  (on your PC)
============================================================
1. Put credentials.json in this folder (next to web_app.py).
2. Double-click run_website.bat   (or: python web_app.py)
3. Open http://127.0.0.1:5000
No password is needed locally.


============================================================
 B) MAKE IT LIVE  (free, via GitHub + Render)
============================================================

STEP 1 - Put the code on GitHub
-------------------------------
In this folder:
    git init
    git add .
    git commit -m "Compliance data website"
Then create an EMPTY repo on github.com (Private is best) and:
    git branch -M main
    git remote add origin https://github.com/<you>/<repo>.git
    git push -u origin main

Double-check: credentials.json must NOT appear on GitHub.
(.gitignore prevents it - verify by looking at the repo online.)


STEP 2 - Create the service on Render
-------------------------------------
    - Go to https://render.com and sign in with GitHub (free, no card).
    - New +  ->  Web Service  ->  pick your repo.
    - Render auto-detects Python. Confirm:
         Build command:  pip install -r requirements.txt
         Start command:  gunicorn web_app:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT
      (These are also in the Procfile, so it usually fills them in.)
    - Instance type:  Free.


STEP 3 - Add your Google key as a Secret File
---------------------------------------------
    - In the service, open  Environment  ->  Secret Files.
    - Add file:
         Filename:  credentials.json
         Contents:  paste the ENTIRE contents of your credentials.json
    - Save. (Render mounts it at /etc/secrets/credentials.json - the
      app already knows to look there.)


STEP 4 - Add a password  (strongly recommended)
-----------------------------------------------
This tool has no login of its own, so protect the public URL:
    - Environment  ->  Environment Variables  ->  Add:
         Key:    APP_PASSWORD
         Value:  <choose a strong password>
    - Save. The browser will now ask for a login on every visit.
      (Username = anything, Password = what you set.)


STEP 5 - Deploy + share
-----------------------
    - Render builds and gives you a URL like
         https://techno-compliance.onrender.com
    - Share that URL + the password with whoever needs it.


THINGS TO KNOW ABOUT THE FREE TIER
----------------------------------
- The service SLEEPS after 15 minutes of no traffic. The first
  visit after that takes ~30-60 seconds to wake up (normal).
- 750 free hours/month - plenty for an internal tool.
- Storage is temporary: the web_output/ CSVs are wiped on
  restart. That's fine because users download immediately.
- Keep it on ONE worker (the Procfile does this). The live
  progress bar relies on shared in-memory state, which only
  works with a single worker.
- "All Markets" scans every sheet incl. Houston/Memphis extras
  and the LA/Houston folders, so it can take a few minutes.

To grant the service account access: the Google service account
email in credentials.json must be shared (Viewer) on the market
sheets/folders - same as your importer already uses.

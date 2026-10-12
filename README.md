# Village Hobbies Racing site

## First-time setup
1. Install Python 3.10+.
2. In this folder: `pip install -r requirements.txt`
3. Open `config.py` and set ADMIN_USERNAME, ADMIN_PASSWORD and SECRET_KEY (admin login stays disabled until you do).
4. `python app.py`, then open http://localhost:5000
5. Log in at /admin (there is a small "Admin" link in the footer), then Race days -> upload a zip of each race day folder.

## Adding race days
Zip the race day folder (the one containing the `html` folder), e.g. `7 SEP 2026.zip`, and upload it in Admin -> Race days.
Pick Oval or Offroad. The date is read from the zip name if you leave it blank.
You can also import from the command line: `python importer.py "7 SEP 2026" offroad`

## What to back up
- `data/vhr.db`  (all race data, news, names, settings)
- `static/uploads/`  (approved photos, news and home page images)
Copy these two somewhere safe regularly. Everything else can be re-downloaded.

## Running for the public
`python app.py` is fine for testing. For a real site use a production server, for example:
`pip install gunicorn` then `gunicorn -w 2 -b 0.0.0.0:8000 app:app`
and put it behind HTTPS (your host or a reverse proxy like Caddy/nginx can do this).

## Changing the look
Colors are at the top of `static/css/style.css` (--accent is the green).
Site name and tagline are in `config.py`.

## Requirements
Any computer with a network and python.
Laps Free (I hope the best of luck with this one)

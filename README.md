# Village Hobbies Racing site

## First-time setup
1. Install Python 3.10+.
2. In this folder: `pip install -r requirements.txt`
3. Open `config.py` and set ADMIN_USERNAME, ADMIN_PASSWORD and SECRET_KEY (admin login stays disabled until you do).
4. `python app.py`, then open http://localhost:5000
5. Log in at /admin (there is a small "Admin" link in the footer), then Race days -> upload a zip of each race day folder.

To give another person their own login, set `ADMIN_USERNAME_2` and `ADMIN_PASSWORD_2` in your deployed `config.py` and restart the app. Use a different username for each account. Both logins have full access to the admin panel.

## Adding race days
Zip the race day folder (the one containing the `html` folder), e.g. `7 SEP 2026.zip`, and upload it in Admin -> Race days.
Pick Oval or Offroad. The date is read from the zip name if you leave it blank.
You can also import from the command line: `python importer.py "7 SEP 2026" offroad`

## Updating an existing site
Deploy the updated application files with your existing `config.py`, `data/vhr.db` and `static/uploads/`. The app adds the date-rule table when it starts. Existing race data, driver name mappings, photos and pending submissions carry over.

## Driver names and lap times
Under **Admin → Driver names**, add a date rule to split a reused timing name. For example, leave older results under `DAVE` and add a rule for `DAVE 2026` starting on `2026-01-01`. Leave the end date blank if future results should go to the newer driver too. The original profile URL still serves the older results as long as they display as `DAVE`.

Under **Admin → Lap settings**, set the minimum in seconds for each track. Oval starts at 5 seconds and offroad starts at 0, which includes all positive offroad lap times. Times equal to the minimum qualify. Changes apply immediately to existing and future race results on the site.

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

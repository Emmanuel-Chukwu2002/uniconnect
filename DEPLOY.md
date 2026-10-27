# Putting UniConnect online (Render)

UniConnect is ready for [Render](https://render.com): `render.yaml` creates the
website and a PostgreSQL database and connects them, and `build.sh` runs on every
deploy (installs packages, gathers the CSS/JS with WhiteNoise, updates the tables).
The site runs on Daphne, so the real-time chat works online too.

Nothing changes on your laptop: there DEBUG stays on and `.env` is used as before.

## 1. Put the code on GitHub

Create an **empty private repository** on github.com (e.g. `uniconnect`), then in the
project folder:

```
git init
git add .
git commit -m "UniConnect"
git branch -M main
git remote add origin https://github.com/<your-username>/uniconnect.git
git push -u origin main
```

`.gitignore` keeps `.env` (your passwords and keys), `db.sqlite3`, `media/`,
`backups/` and `staticfiles/` off GitHub.

## 2. Create it on Render

1. Sign up at render.com with your GitHub account.
2. **New + → Blueprint**, pick the `uniconnect` repository, then **Apply**.
   Render reads `render.yaml` and creates `uniconnect-db` (PostgreSQL) and the
   `uniconnect` web service. The first build takes a few minutes.
3. Open the **uniconnect** service → **Environment** and fill in the values marked
   "sync: false" — the same ones as in your `.env`: `IMAGEKIT_PUBLIC_KEY`,
   `IMAGEKIT_PRIVATE_KEY`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and, if you use
   Google sign-in, `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. Save (it redeploys).
4. Your site is at `https://uniconnect-xxxx.onrender.com` (shown at the top of the
   service page). For Google sign-in, add that address to the OAuth client's
   authorised origins and redirect URIs in Google Cloud Console.

## 3. Copy your data up (optional)

The online database starts empty (the tables are built, no accounts). To copy your
laptop's data into it:

1. On your laptop: `python manage.py backup_db` → note the file name in `backups\`.
2. On Render: **uniconnect-db → Connect → External Database URL** — copy it.
3. In the VS Code terminal (PowerShell), point this one terminal at the online
   database and restore:
   ```
   $env:DATABASE_URL="<the External Database URL>"
   python manage.py restore_db backups\uniconnect-<date>.dump
   Remove-Item Env:DATABASE_URL
   ```
   The same trick runs any command online, e.g. `python manage.py createsuperuser`
   or `python manage.py clear_sample_data`.

## Things to know about the free plan

- The website sleeps after about 15 minutes without visitors; the first visit
  after that takes up to a minute to wake it. Open it a minute before a demo.
- Free databases are time-limited on Render — check the date on the
  uniconnect-db page, and keep `backup_db` copies.
- **Uploaded files:** the free website has no permanent disk, so files saved in
  `media/` (course notes, group files, uploads made while ImageKit isn't set up)
  disappear on the next deploy. Photos and videos go to ImageKit once its keys are
  set, so they're safe. For everything else, add a Render **Disk** (paid) mounted
  at `/var/data` and set `MEDIA_ROOT=/var/data/media`.
- Chat uses one in-memory channel layer, which is right for one running instance
  (the free plan). For several instances, switch `CHANNEL_LAYERS` to Redis
  (see the comment in `uniconnect/settings.py`).

## Updating the site

Commit and push; Render redeploys by itself:

```
git add .
git commit -m "What changed"
git push
```

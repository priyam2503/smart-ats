# Deploying to Render (free tier)

This app is a **Flask** server (`app.py`). It is deployed to Render using the
`render.yaml` blueprint in this folder.

## One-time steps

1. Go to <https://dashboard.render.com> and sign up / log in (GitHub login is easiest).
2. Click **New +** → **Blueprint**.
3. Connect your GitHub and pick the repo **`Antra-light/Smart-ATS-Web-App`**.
4. Render reads `render.yaml` and shows the service `smart-ats`. Click **Apply**.
5. Render will ask you to fill in the secret values (the ones marked `sync: false`).
   Copy each value from your **local `.env`** file:
   - `GOOGLE_API_KEY`
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`
6. Click **Create** / **Deploy** and wait ~3–5 minutes for the first build.
7. Your live URL appears at the top, like `https://smart-ats.onrender.com`.

## Important free-tier notes

- **The app sleeps after ~15 minutes of no visitors.** The next visit takes
  ~30–50 seconds to wake it up, then it's fast again.
- **The database is temporary.** Render's free plan does not keep files between
  restarts, so accounts and saved evaluations reset whenever the app sleeps or
  redeploys. This is fine for a demo. To make data permanent, upgrade to a paid
  plan with a disk, or switch the app from SQLite to a cloud Postgres database.

## Updating the live site later

Every time you `git push` to the `main` branch, Render automatically rebuilds
and redeploys. No extra steps.

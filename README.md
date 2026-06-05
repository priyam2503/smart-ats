# Smart ATS — AI Resume Analyzer 📄🤖

<div align="center">

### 🔗 [**Try the Live Demo →**](https://smart-ats-shlf.onrender.com)

*Free hosting — the first visit may take ~30–50s to wake the app, then it's fast.*

</div>

---

An AI-powered **Applicant Tracking System (ATS)** that scores your résumé against any
job description, tells you exactly which keywords you're missing, and helps you fix
them — powered by Google Gemini.

Upload a résumé (PDF, scanned PDF, or image), paste a job description, and get an
instant, recruiter-style breakdown: a match score, missing keywords grouped by
priority, an ATS-health check, and AI tools to rewrite your bullet points and prep
for the interview.

> Built with **Python + Flask** and **Google Gemini**. Deploys free on Render.

---

## ✨ Features

### 🎯 Resume vs. Job Description analysis
- **JD Match score** (%) — how well your résumé fits the role
- **Missing keywords, triaged** into:
  - **Must-have** — core skills the job clearly requires that you're missing
  - **Nice-to-have** — bonus keywords worth adding
  - **Quick wins** — easy, *honest* keywords plus a one-line "how to add it"
- **Entry-level warning** — flags when a job secretly wants 3+ years of experience
- **ATS health check** — catches formatting issues that confuse real ATS software
- **Profile summary** — a specific, actionable read on your résumé
- **Reads any format** — text PDFs, *scanned* PDFs, and image résumés (PNG/JPG) via
  Gemini vision. The same résumé always gets the **same score** (deterministic AI), so
  a PDF and its screenshot grade identically.

### 🧰 Career Toolkit (one click from any analysis)
Generates a tailored cover letter, likely interview questions, résumé tips, a skill
roadmap, an elevator pitch, LinkedIn suggestions, and career-pivot advice.

### ✍️ Experience & Keyword Coach
Writes strong, ATS-friendly résumé bullets in **XYZ / STAR** form, weaving in the job's
keywords — perfect for freshers and career-switchers. It **never fabricates** employers,
dates, or metrics; unknown numbers become `[X]` placeholders for you to fill in.

### 👤 Accounts, history & dashboard
- Sign up with **email OTP verification**, log in, and reset forgotten passwords
- Passwords are **hashed** (never stored in plain text); sessions are hardened
- Your past evaluations are **saved per account** with a stats dashboard

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python, Flask, Flask-CORS, Gunicorn |
| **AI** | Google Gemini (`google-generativeai`) — `gemini-2.5-flash` |
| **PDF parsing** | PyPDF2 (text) + Gemini vision (scanned/image résumés) |
| **Database** | SQLite (`ats.db`) |
| **Auth** | Werkzeug password hashing + server-side sessions |
| **Email** | Gmail API (HTTPS) · Brevo (HTTPS) · SMTP (local fallback) |
| **Frontend** | Single-page HTML / CSS / JavaScript |
| **Hosting** | Render (free tier) via `render.yaml` blueprint |

---

## 🚀 Run it locally

### 1. Get the code
```bash
git clone https://github.com/priyam2503/smart-ats.git
cd smart-ats
```

### 2. Create a virtual environment & install dependencies
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Add your secret keys
Create a file named **`.env`** in the project folder (it's gitignored — it never gets
committed) with at least:

```env
# Required — get a free key at https://aistudio.google.com/app/apikey
GOOGLE_API_KEY=your_gemini_api_key_here

# Optional
GEMINI_MODEL=gemini-2.5-flash
```

> **Email is optional for local use.** Sign-up OTP and password-reset emails only send
> if you also add email credentials (Gmail API, Brevo, or SMTP). Without them, the core
> résumé analysis still works — see [`DEPLOY.md`](DEPLOY.md) for the full email setup.

### 4. Start the app
```bash
python app.py
```
Open **http://localhost:5000** in your browser. 🎉

---

## ☁️ Deploy (free on Render)

This repo includes a `render.yaml` blueprint, so deployment is mostly point-and-click.
Full step-by-step instructions — including the Gmail/Brevo email setup needed because
Render blocks outbound SMTP — are in **[`DEPLOY.md`](DEPLOY.md)**.

In short: create a new **Blueprint** on [Render](https://dashboard.render.com), point it
at this repo, and paste your secret values when prompted. Every `git push` to `main`
then auto-redeploys.

> **Free-tier note:** the app sleeps after ~15 min idle (first visit takes ~30–50s to
> wake), and the SQLite database resets on redeploy — fine for a demo, but use a paid
> disk or cloud Postgres to keep data permanently.

---

## 🔑 Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ | Your Google Gemini API key |
| `GEMINI_MODEL` | — | Model override (default `gemini-2.5-flash`) |
| `FLASK_SECRET` | — | Session signing key (auto-generated if unset) |
| `HTTPS` | — | Set to `1` in production to mark cookies Secure |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` / `GMAIL_SENDER` | — | Send OTP / reset email via Gmail API |
| `BREVO_API_KEY` | — | Alternative HTTPS email provider |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | — | Local-dev email fallback |

Secrets live only in your local `.env` or your host's settings — **never** in this repo.

---

## 📁 Project structure

```
smart-ats/
├── app.py               # Flask server: routes, Gemini calls, auth, SQLite
├── get_gmail_token.py   # One-time helper to obtain a Gmail API refresh token
├── requirements.txt     # Python dependencies
├── render.yaml          # Render deployment blueprint
├── DEPLOY.md            # Full deployment + email setup guide
├── templates/
│   └── index.html       # Single-page frontend
└── static/
    ├── css/ · style.css # Styles
    └── js/  · script.js # Frontend logic
```

---

## 📌 Notes & limitations

- The free Gemini tier has a **daily request limit** — heavy testing can hit a temporary
  rate limit (the app shows a clear message instead of failing silently).
- On Render's free plan, accounts and saved evaluations **reset on redeploy** (see above).

---

<div align="center">
Made with ☕ and a lot of résumé tweaking.
</div>

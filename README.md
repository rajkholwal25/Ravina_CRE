# Handbook of Dialysis — Quiz Practice App

An MCQ practice web app built from **Handbook of Dialysis, 5th Edition (Daugirdas)**.
All 40 chapters have 50+ multiple-choice questions, each with the correct answer and a
5–6 line explanation. Data lives in **Supabase (Postgres)**; users sign up by email,
take chapter-wise or cross-chapter quizzes, and every attempt is saved to their account.

## Features
- **Accounts** — email sign up / log in, plus **forgot-password** (emailed reset link).
- **Quizzes** — pick one chapter, several, or all; choose how many questions.
- **Instant feedback** — correct answer + full explanation on every question.
- **Two timers** — total quiz time and per-question time (both survive a page refresh).
- **Saved results** — review any past quiz in-app or **download it as a PDF** (includes
  per-question time and explanations).
- **Weak areas** — chapters where you get the most wrong, ranked.
- **Admin dashboard** (`admin@test.com`) — see all users, their last-quiz time, scores,
  and drill into any quiz.

## Run locally (Windows)
```
cd dialysis_quiz
python -m pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 — you'll land on the login page. Create an account, then log in.

Credentials/config are read from `dialysis_quiz/.env` (not committed). Keys used:
`PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE SECRET_KEY BREVO_API_KEY MAIL_FROM_EMAIL
MAIL_FROM_NAME`.

## Data & database
- Source of truth for questions is `questions_json/chNN.json` → loaded into local
  `quiz.db` via `init_db.py` + `load_questions.py`.
- `migrate_to_supabase.py` pushes `quiz.db` into Supabase (idempotent).
- The app reads/writes Supabase at runtime. Tables: `dialysis_chapters`,
  `dialysis_questions`, `dialysis_users`, `dialysis_results`. `app.py` auto-creates/upgrades
  tables and seeds the admin account on startup (`ensure_schema`).

## Email (password reset) — Brevo
Reset emails are sent via **Brevo's HTTPS API** (`BREVO_API_KEY`, `MAIL_FROM_EMAIL`,
`MAIL_FROM_NAME`). We use an HTTPS API rather than SMTP because **Render blocks outbound
SMTP ports** (25/465/587).

Brevo setup (in the Brevo dashboard):
1. **Senders** → verify `MAIL_FROM_EMAIL` as a sender (Brevo emails it a confirmation link).
2. **Security → Authorized IPs** → turn OFF the IP restriction (Render's IP is dynamic),
   otherwise the API returns 401 "unrecognised IP address".

Once the sender is verified, Brevo can email any recipient (free tier ~300/day).

## Deploy to Render (free) + keep-awake
1. Push the `dialysis_quiz/` folder to a GitHub repo.
2. In Render: **New + → Blueprint**, select the repo (uses `render.yaml`).
3. Set the secret env vars in the Render dashboard: `PGHOST PGPORT PGUSER PGPASSWORD
   PGDATABASE BREVO_API_KEY MAIL_FROM_EMAIL` (SECRET_KEY is auto-generated).
4. After it's live, copy the URL (e.g. `https://dialysis-quiz.onrender.com`).
5. In the GitHub repo: **Settings → Secrets and variables → Actions → Variables**, add
   `RENDER_URL` = your Render URL. The workflow in `.github/workflows/keepalive.yml`
   pings `/healthz` every ~10 min so the free instance doesn't spin down.

## Notes
Questions and explanations are generated from the book for personal exam practice —
always defer to your official course materials and guidelines.

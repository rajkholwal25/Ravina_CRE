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
`PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE SECRET_KEY RESEND_API_KEY RESEND_FROM`.

## Data & database
- Source of truth for questions is `questions_json/chNN.json` → loaded into local
  `quiz.db` via `init_db.py` + `load_questions.py`.
- `migrate_to_supabase.py` pushes `quiz.db` into Supabase (idempotent).
- The app reads/writes Supabase at runtime. Tables: `dialysis_chapters`,
  `dialysis_questions`, `dialysis_users`, `dialysis_results`. `app.py` auto-creates/upgrades
  tables and seeds the admin account on startup (`ensure_schema`).

## Email (password reset) — important
Reset emails are sent via **Resend**. A brand-new Resend account is in **test mode** and
can only deliver to the account owner's email. To send reset links to *any* user:
1. Verify a domain at https://resend.com/domains
2. Set `RESEND_FROM` to an address at that domain (e.g. `Quiz <no-reply@yourdomain.com>`).

## Deploy to Render (free) + keep-awake
1. Push the `dialysis_quiz/` folder to a GitHub repo.
2. In Render: **New + → Blueprint**, select the repo (uses `render.yaml`).
3. Set the secret env vars in the Render dashboard: `PGHOST PGPORT PGUSER PGPASSWORD
   PGDATABASE RESEND_API_KEY` (SECRET_KEY is auto-generated).
4. After it's live, copy the URL (e.g. `https://dialysis-quiz.onrender.com`).
5. In the GitHub repo: **Settings → Secrets and variables → Actions → Variables**, add
   `RENDER_URL` = your Render URL. The workflow in `.github/workflows/keepalive.yml`
   pings `/healthz` every ~10 min so the free instance doesn't spin down.

## Notes
Questions and explanations are generated from the book for personal exam practice —
always defer to your official course materials and guidelines.

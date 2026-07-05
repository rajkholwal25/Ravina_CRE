"""Dialysis Handbook Quiz — Flask app backed by Supabase (Postgres).

Features:
- Questions/chapters read from Supabase (dialysis_chapters, dialysis_questions).
- Email sign up / log in; sessions in a signed cookie.
- Forgot-password via emailed reset link (Resend API).
- Each finished quiz saved per user (dialysis_results): review in-app, download PDF
  (with per-question time), weak-area analysis.
- Admin dashboard (admin@test.com): list users, last-quiz time, scores, view any quiz.

Run locally:  python app.py    Prod:  gunicorn app:app
"""
import io
import os
import secrets
import json
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    path = os.path.join(BASE, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Trust Render's / any reverse proxy so request.host_url uses the real https scheme
# (needed for correct password-reset links behind TLS termination).
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "Dialysis Quiz <onboarding@resend.dev>")

POOL = ThreadedConnectionPool(
    1, int(os.environ.get("POOL_MAX", "4")),
    host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
    user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
    dbname=os.environ.get("PGDATABASE", "postgres"), connect_timeout=20,
)


def db():
    if "conn" not in g:
        conn = POOL.getconn()
        conn.autocommit = True
        g.conn = conn
    return g.conn


def q(sql, params=None, one=False):
    cur = db().cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params or ())
    if cur.description is None:
        return None
    return cur.fetchone() if one else cur.fetchall()


@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("conn", None)
    if conn is not None:
        POOL.putconn(conn)


# ----------------------------------------------------------------- schema setup
def ensure_schema():
    """Create/upgrade tables and seed the admin account (idempotent)."""
    conn = POOL.getconn()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dialysis_chapters (
            num INTEGER PRIMARY KEY, title TEXT NOT NULL, part TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dialysis_questions (
            id BIGSERIAL PRIMARY KEY, chapter_num INTEGER NOT NULL,
            topic TEXT, question TEXT NOT NULL,
            option_a TEXT NOT NULL, option_b TEXT NOT NULL,
            option_c TEXT NOT NULL, option_d TEXT NOT NULL,
            correct TEXT NOT NULL, explanation TEXT NOT NULL,
            UNIQUE (chapter_num, question));
        CREATE TABLE IF NOT EXISTS dialysis_users (
            id BIGSERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, name TEXT,
            created_at TIMESTAMPTZ DEFAULT now());
        ALTER TABLE dialysis_users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT false;
        ALTER TABLE dialysis_users ADD COLUMN IF NOT EXISTS reset_token TEXT;
        ALTER TABLE dialysis_users ADD COLUMN IF NOT EXISTS reset_expires TIMESTAMPTZ;
        CREATE TABLE IF NOT EXISTS dialysis_results (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES dialysis_users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT now(), chapters TEXT,
            num_questions INT NOT NULL, score INT NOT NULL, total INT NOT NULL,
            duration_seconds INT NOT NULL DEFAULT 0, details JSONB NOT NULL DEFAULT '[]');
        CREATE INDEX IF NOT EXISTS idx_dr_user ON dialysis_results(user_id);
    """)
    cur.execute("SELECT id FROM dialysis_users WHERE email=%s", ("admin@test.com",))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO dialysis_users (email, password_hash, name, is_admin) VALUES (%s,%s,%s,true)",
            ("admin@test.com", generate_password_hash("admin"), "Administrator"))
    POOL.putconn(conn)


try:
    ensure_schema()
except Exception as e:  # don't crash on boot if DB is briefly unreachable
    print("ensure_schema warning:", e)


# ----------------------------------------------------------------- auth utils
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return q("SELECT id, email, name, is_admin FROM dialysis_users WHERE id=%s", (uid,), one=True)


def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("uid"):
            return jsonify({"error": "Please log in."}), 401
        return f(*a, **k)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        u = current_user()
        if not u or not u["is_admin"]:
            return jsonify({"error": "Admins only."}), 403
        return f(*a, **k)
    return wrapper


def send_email(to, subject, html):
    """Send an email via Resend. Returns (ok, message)."""
    if not RESEND_API_KEY:
        return False, "Email is not configured (missing RESEND_API_KEY)."
    payload = json.dumps({"from": RESEND_FROM, "to": [to],
                          "subject": subject, "html": html}).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "dialysis-quiz/1.0 (+https://resend.com)",
                 "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return True, r.read().decode()
    except urllib.error.HTTPError as e:
        return False, f"{e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return False, str(e)


# ----------------------------------------------------------------- page routes
@app.route("/")
def index():
    if not session.get("uid"):
        return redirect(url_for("login_page"))
    return render_template("index.html")


@app.route("/login")
def login_page():
    if session.get("uid"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/signup")
def signup_page():
    if session.get("uid"):
        return redirect(url_for("index"))
    return render_template("signup.html")


@app.route("/forgot")
def forgot_page():
    return render_template("forgot.html")


@app.route("/reset/<token>")
def reset_page(token):
    return render_template("reset.html", token=token)


@app.route("/admin")
def admin_page():
    u = current_user()
    if not u:
        return redirect(url_for("login_page"))
    if not u["is_admin"]:
        return redirect(url_for("index"))
    return render_template("admin.html")


# ----------------------------------------------------------------- auth api
@app.post("/api/signup")
def api_signup():
    d = request.get_json(force=True)
    email = (d.get("email") or "").strip().lower()
    pw = d.get("password") or ""
    name = (d.get("name") or "").strip()
    if "@" not in email or "." not in email:
        return jsonify({"error": "Please enter a valid email address."}), 400
    if len(pw) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if q("SELECT 1 FROM dialysis_users WHERE email=%s", (email,), one=True):
        return jsonify({"error": "An account with this email already exists. Please log in."}), 409
    q("INSERT INTO dialysis_users (email, password_hash, name) VALUES (%s,%s,%s)",
      (email, generate_password_hash(pw), name))
    return jsonify({"ok": True, "message": "Account created. Please log in."})


@app.post("/api/login")
def api_login():
    d = request.get_json(force=True)
    email = (d.get("email") or "").strip().lower()
    pw = d.get("password") or ""
    u = q("SELECT * FROM dialysis_users WHERE email=%s", (email,), one=True)
    if not u or not check_password_hash(u["password_hash"], pw):
        return jsonify({"error": "Invalid email or password."}), 401
    session["uid"] = u["id"]
    session.permanent = True
    return jsonify({"ok": True, "email": u["email"], "name": u["name"], "is_admin": u["is_admin"]})


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    return jsonify({"user": current_user()})


@app.post("/api/forgot")
def api_forgot():
    d = request.get_json(force=True)
    email = (d.get("email") or "").strip().lower()
    u = q("SELECT id, email FROM dialysis_users WHERE email=%s", (email,), one=True)
    # Always report success so we don't reveal which emails are registered.
    generic = {"ok": True, "message": "If that email has an account, a reset link is on its way."}
    if not u:
        return jsonify(generic)
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    q("UPDATE dialysis_users SET reset_token=%s, reset_expires=%s WHERE id=%s",
      (token, expires, u["id"]))
    link = request.host_url.rstrip("/") + url_for("reset_page", token=token)
    html = f"""
      <div style="font-family:Segoe UI,Arial,sans-serif;max-width:480px;margin:auto">
        <h2 style="color:#155a97">Reset your password</h2>
        <p>We received a request to reset the password for your Dialysis Quiz account.</p>
        <p><a href="{link}" style="display:inline-block;background:#1d6fb8;color:#fff;
           padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600">
           Reset password</a></p>
        <p style="color:#666;font-size:13px">This link expires in 1 hour. If you didn't
           request this, you can ignore this email.</p>
        <p style="color:#888;font-size:12px">Or paste this link:<br>{link}</p>
      </div>"""
    ok, msg = send_email(u["email"], "Reset your Dialysis Quiz password", html)
    if not ok:
        return jsonify({"ok": False, "error": "Could not send email: " + msg}), 502
    return jsonify(generic)


@app.post("/api/reset")
def api_reset():
    d = request.get_json(force=True)
    token = (d.get("token") or "").strip()
    pw = d.get("password") or ""
    if len(pw) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    u = q("SELECT id, reset_expires FROM dialysis_users WHERE reset_token=%s", (token,), one=True)
    if not u or not u["reset_expires"] or u["reset_expires"] < datetime.now(timezone.utc):
        return jsonify({"error": "This reset link is invalid or has expired."}), 400
    q("UPDATE dialysis_users SET password_hash=%s, reset_token=NULL, reset_expires=NULL WHERE id=%s",
      (generate_password_hash(pw), u["id"]))
    return jsonify({"ok": True, "message": "Password updated. Please log in."})


# ----------------------------------------------------------------- quiz api
@app.get("/api/chapters")
@login_required
def api_chapters():
    rows = q("""SELECT c.num, c.title, c.part,
                  (SELECT COUNT(*) FROM dialysis_questions q WHERE q.chapter_num=c.num) AS n
                FROM dialysis_chapters c ORDER BY c.num""")
    total = q("SELECT COUNT(*) AS n FROM dialysis_questions", one=True)["n"]
    return jsonify({"total": total, "chapters": rows})


@app.get("/api/quiz")
@login_required
def api_quiz():
    import random
    chapters = request.args.get("chapters", "all")
    limit = int(request.args.get("limit", "20"))
    if chapters != "all":
        nums = [int(x) for x in chapters.split(",") if x.strip().isdigit()]
        rows = q("SELECT * FROM dialysis_questions WHERE chapter_num = ANY(%s)", (nums,)) if nums else []
    else:
        rows = q("SELECT * FROM dialysis_questions")
    rows = list(rows)
    random.shuffle(rows)
    out = []
    for r in rows:
        opts = {"A": r["option_a"], "B": r["option_b"], "C": r["option_c"], "D": r["option_d"]}
        items = list(opts.items())
        random.shuffle(items)
        out.append({"id": r["id"], "chapter_num": r["chapter_num"],
                    "topic": r["topic"], "question": r["question"],
                    "options": {k: v for k, v in items}})
    if limit and limit > 0:
        out = out[:limit]
    return jsonify({"questions": out, "count": len(out)})


@app.post("/api/answer")
@login_required
def api_answer():
    d = request.get_json(force=True)
    qid = int(d["id"])
    chosen = (d.get("chosen") or "").strip().upper()
    r = q("SELECT * FROM dialysis_questions WHERE id=%s", (qid,), one=True)
    if r is None:
        return jsonify({"error": "unknown question"}), 404
    return jsonify({
        "correct_option": r["correct"],
        "correct_text": r["option_" + r["correct"].lower()],
        "is_correct": chosen == r["correct"],
        "explanation": r["explanation"],
        "topic": r["topic"],
    })


@app.post("/api/submit")
@login_required
def api_submit():
    d = request.get_json(force=True)
    details = d.get("details", []) or []
    total = len(details)
    score = sum(1 for x in details if x.get("is_correct"))
    dur = int(d.get("duration_seconds", 0) or 0)
    chapters = str(d.get("chapters", "all"))
    row = q("""INSERT INTO dialysis_results
                 (user_id, chapters, num_questions, score, total, duration_seconds, details)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (session["uid"], chapters, total, score, total, dur, Json(details)), one=True)
    return jsonify({"ok": True, "id": row["id"], "score": score, "total": total})


@app.get("/api/results")
@login_required
def api_results():
    rows = q("""SELECT id, created_at, chapters, score, total, duration_seconds
                FROM dialysis_results WHERE user_id=%s ORDER BY created_at DESC""",
             (session["uid"],))
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return jsonify({"results": rows})


def _fetch_result(rid):
    """Return a result row the current user may view (own, or any if admin)."""
    u = current_user()
    res = q("SELECT * FROM dialysis_results WHERE id=%s", (rid,), one=True)
    if not res:
        return None
    if res["user_id"] != u["id"] and not u["is_admin"]:
        return None
    return res


def _result_items(res):
    details = res["details"] or []
    ids = [x.get("id") for x in details if x.get("id") is not None]
    qmap = {}
    if ids:
        for row in q("SELECT * FROM dialysis_questions WHERE id = ANY(%s)", (ids,)):
            qmap[row["id"]] = row
    items = []
    for i, x in enumerate(details, 1):
        row = qmap.get(x.get("id"))
        if not row:
            continue
        chosen = (x.get("chosen") or "").upper()
        chosen_text = row.get("option_" + chosen.lower()) if chosen in ("A", "B", "C", "D") else None
        items.append({
            "n": i, "chapter_num": row["chapter_num"], "topic": row["topic"],
            "question": row["question"],
            "chosen": chosen, "chosen_text": chosen_text,
            "correct": row["correct"], "correct_text": row["option_" + row["correct"].lower()],
            "is_correct": bool(x.get("is_correct")), "explanation": row["explanation"],
            "time_spent": int(x.get("time_spent") or 0),
        })
    return items


@app.get("/api/results/<int:rid>")
@login_required
def api_result_detail(rid):
    res = _fetch_result(rid)
    if not res:
        abort(404)
    owner = q("SELECT email, name FROM dialysis_users WHERE id=%s", (res["user_id"],), one=True)
    return jsonify({
        "result": {
            "id": res["id"], "created_at": res["created_at"].isoformat(),
            "chapters": res["chapters"], "score": res["score"], "total": res["total"],
            "duration_seconds": res["duration_seconds"],
            "owner_email": owner["email"] if owner else "",
        },
        "items": _result_items(res),
    })


@app.get("/api/weak")
@login_required
def api_weak():
    rows = q("SELECT details FROM dialysis_results WHERE user_id=%s", (session["uid"],))
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        for x in (r["details"] or []):
            ch = x.get("chapter_num")
            if ch is None:
                continue
            agg[ch][1] += 1
            if not x.get("is_correct"):
                agg[ch][0] += 1
    titles = {c["num"]: c["title"] for c in q("SELECT num, title FROM dialysis_chapters")}
    weak = [{"chapter": ch, "title": titles.get(ch, ""), "wrong": w, "total": t,
             "pct": round(100 * w / t) if t else 0}
            for ch, (w, t) in agg.items()]
    weak.sort(key=lambda z: (-z["pct"], -z["wrong"]))
    return jsonify({"weak": weak, "answered": sum(t for _, t in agg.values())})


# ----------------------------------------------------------------- admin api
@app.get("/api/admin/users")
@admin_required
def api_admin_users():
    rows = q("""SELECT u.id, u.email, u.name, u.is_admin, u.created_at,
                       COUNT(r.id) AS quizzes, MAX(r.created_at) AS last_quiz,
                       COALESCE(SUM(r.score),0) AS total_correct,
                       COALESCE(SUM(r.total),0) AS total_answered
                FROM dialysis_users u
                LEFT JOIN dialysis_results r ON r.user_id=u.id
                GROUP BY u.id ORDER BY last_quiz DESC NULLS LAST, u.created_at DESC""")
    for r in rows:
        r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        r["last_quiz"] = r["last_quiz"].isoformat() if r["last_quiz"] else None
    return jsonify({"users": rows})


@app.get("/api/admin/users/<int:uid>/results")
@admin_required
def api_admin_user_results(uid):
    owner = q("SELECT email, name FROM dialysis_users WHERE id=%s", (uid,), one=True)
    if not owner:
        abort(404)
    rows = q("""SELECT id, created_at, chapters, score, total, duration_seconds
                FROM dialysis_results WHERE user_id=%s ORDER BY created_at DESC""", (uid,))
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return jsonify({"owner": owner, "results": rows})


# ----------------------------------------------------------------- PDF export
def _result_pdf(rid):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    res = _fetch_result(rid)
    if not res:
        abort(404)
    owner = q("SELECT email FROM dialysis_users WHERE id=%s", (res["user_id"],), one=True)
    items = _result_items(res)

    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], fontSize=18, textColor=colors.HexColor("#155a97"))
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#555555"))
    qs = ParagraphStyle("qs", parent=styles["Normal"], fontSize=10.5, spaceBefore=8, spaceAfter=2, leading=14)
    ok = ParagraphStyle("ok", parent=styles["Normal"], fontSize=9.5, textColor=colors.HexColor("#1a8f4c"), leading=13)
    bad = ParagraphStyle("bad", parent=styles["Normal"], fontSize=9.5, textColor=colors.HexColor("#c62828"), leading=13)
    ex = ParagraphStyle("ex", parent=styles["Normal"], fontSize=9.5, textColor=colors.HexColor("#333333"), leading=13, leftIndent=6)
    tm = ParagraphStyle("tm", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#888888"), leading=12)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm, title=f"Quiz Result {rid}")
    pct = round(100 * res["score"] / res["total"]) if res["total"] else 0
    mins, secs = divmod(res["duration_seconds"], 60)
    story = [Paragraph("Handbook of Dialysis — Quiz Result", h)]
    story.append(Paragraph(f"{owner['email']} &nbsp;·&nbsp; {res['created_at'].strftime('%d %b %Y, %H:%M')}", sub))
    story.append(Paragraph(
        f"Chapters: {res['chapters']} &nbsp;·&nbsp; Score: <b>{res['score']}/{res['total']} ({pct}%)</b>"
        f" &nbsp;·&nbsp; Total time: {mins}m {secs}s", sub))
    story.append(Spacer(1, 8))

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    for it in items:
        story.append(Paragraph(f"<b>Q{it['n']}.</b> (Ch {it['chapter_num']}) {esc(it['question'])}", qs))
        story.append(Paragraph(f"⏱ Time on this question: {it['time_spent']}s", tm))
        chosen_txt = it["chosen_text"] or "(no answer)"
        if it["is_correct"]:
            story.append(Paragraph(f"✓ Your answer: {it['chosen']}. {esc(chosen_txt)}", ok))
        else:
            story.append(Paragraph(f"✗ Your answer: {it['chosen']}. {esc(chosen_txt)}", bad))
            story.append(Paragraph(f"✓ Correct: {it['correct']}. {esc(it['correct_text'])}", ok))
        story.append(Paragraph(f"<b>Explanation:</b> {esc(it['explanation'])}", ex))

    doc.build(story)
    buf.seek(0)
    return buf


@app.get("/api/results/<int:rid>/pdf")
@login_required
def api_result_pdf(rid):
    buf = _result_pdf(rid)
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"dialysis-quiz-result-{rid}.pdf")


@app.get("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)

"""Create tables in Supabase Postgres and push all quiz data into them.

Reads credentials from environment (or the local .env file):
  PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

Source of truth is quiz.db (the local SQLite database). Run this after
`python init_db.py` + `python load_questions.py` have populated quiz.db.

Idempotent: tables are created IF NOT EXISTS and rows use ON CONFLICT DO NOTHING,
so re-running will not duplicate data or drop anything.

Usage:  python migrate_to_supabase.py
"""
import os
import sqlite3
import sys

import psycopg2
from psycopg2.extras import execute_values

BASE = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB = os.path.join(BASE, "quiz.db")


def load_env():
    """Minimal .env loader (no external dependency)."""
    path = os.path.join(BASE, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


DDL = """
CREATE TABLE IF NOT EXISTS dialysis_chapters (
    num   INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    part  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dialysis_questions (
    id          BIGSERIAL PRIMARY KEY,
    chapter_num INTEGER NOT NULL REFERENCES dialysis_chapters(num),
    topic       TEXT,
    question    TEXT NOT NULL,
    option_a    TEXT NOT NULL,
    option_b    TEXT NOT NULL,
    option_c    TEXT NOT NULL,
    option_d    TEXT NOT NULL,
    correct     TEXT NOT NULL CHECK (correct IN ('A','B','C','D')),
    explanation TEXT NOT NULL,
    UNIQUE (chapter_num, question)
);

CREATE INDEX IF NOT EXISTS idx_dq_chapter ON dialysis_questions(chapter_num);
"""


def main():
    load_env()
    if not os.path.exists(SQLITE_DB):
        sys.exit("quiz.db not found. Run init_db.py and load_questions.py first.")

    lite = sqlite3.connect(SQLITE_DB)
    lite.row_factory = sqlite3.Row
    chapters = lite.execute(
        "SELECT num, title, part FROM chapters ORDER BY num").fetchall()
    questions = lite.execute(
        """SELECT chapter_num, topic, question, option_a, option_b, option_c,
                  option_d, correct, explanation FROM questions ORDER BY id"""
    ).fetchall()
    lite.close()

    print(f"Read {len(chapters)} chapters and {len(questions)} questions from quiz.db.")

    conn = psycopg2.connect(
        host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"), connect_timeout=20,
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Creating tables (IF NOT EXISTS)...")
    cur.execute(DDL)

    execute_values(
        cur,
        "INSERT INTO dialysis_chapters (num, title, part) VALUES %s "
        "ON CONFLICT (num) DO NOTHING",
        [(c["num"], c["title"], c["part"]) for c in chapters],
    )

    execute_values(
        cur,
        """INSERT INTO dialysis_questions
           (chapter_num, topic, question, option_a, option_b, option_c,
            option_d, correct, explanation) VALUES %s
           ON CONFLICT (chapter_num, question) DO NOTHING""",
        [(q["chapter_num"], q["topic"], q["question"], q["option_a"],
          q["option_b"], q["option_c"], q["option_d"], q["correct"],
          q["explanation"]) for q in questions],
        page_size=200,
    )
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM dialysis_chapters")
    nc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM dialysis_questions")
    nq = cur.fetchone()[0]
    cur.execute("SELECT MIN(length(explanation)), ROUND(AVG(length(explanation))) FROM dialysis_questions")
    mn, av = cur.fetchone()
    conn.close()

    print(f"Supabase now has {nc} chapters and {nq} questions.")
    print(f"Explanation length in Supabase: min {mn}, avg {av} chars.")
    print("Done.")


if __name__ == "__main__":
    main()

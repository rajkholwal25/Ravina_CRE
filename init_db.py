"""Create the SQLite database schema and seed the 40 chapters."""
import sqlite3, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "quiz.db")


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS chapters (
            num   INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            part  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_num INTEGER NOT NULL,
            topic       TEXT,
            question    TEXT NOT NULL,
            option_a    TEXT NOT NULL,
            option_b    TEXT NOT NULL,
            option_c    TEXT NOT NULL,
            option_d    TEXT NOT NULL,
            correct     TEXT NOT NULL CHECK (correct IN ('A','B','C','D')),
            explanation TEXT NOT NULL,
            UNIQUE(chapter_num, question),
            FOREIGN KEY (chapter_num) REFERENCES chapters(num)
        );

        -- Per-attempt log so the app can track progress across sessions.
        CREATE TABLE IF NOT EXISTS attempts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            chosen      TEXT,
            is_correct  INTEGER NOT NULL,
            ts          TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (question_id) REFERENCES questions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_q_chapter ON questions(chapter_num);
        """
    )

    meta_path = os.path.join(BASE, "chapters_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    for m in meta:
        c.execute(
            "INSERT OR REPLACE INTO chapters (num, title, part) VALUES (?,?,?)",
            (m["num"], m["title"], m["part"]),
        )
    conn.commit()
    print(f"DB ready at {DB} with {len(meta)} chapters seeded.")
    conn.close()


if __name__ == "__main__":
    main()

"""Load generated MCQ JSON files (questions_json/chXX.json) into quiz.db.

Each JSON file: {"chapter": <int>, "questions": [
   {"topic": str, "question": str,
    "options": {"A":str,"B":str,"C":str,"D":str},
    "correct": "A|B|C|D", "explanation": str}, ...]}

Idempotent: UNIQUE(chapter_num, question) means re-running skips duplicates.
"""
import sqlite3, json, os, sys, glob

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "quiz.db")
JSON_DIR = os.path.join(BASE, "questions_json")


def load_file(cur, path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ch = int(data["chapter"])
    inserted = skipped = bad = 0
    for q in data["questions"]:
        try:
            opts = q["options"]
            correct = q["correct"].strip().upper()
            if correct not in ("A", "B", "C", "D"):
                bad += 1
                continue
            cur.execute(
                """INSERT OR IGNORE INTO questions
                   (chapter_num, topic, question, option_a, option_b,
                    option_c, option_d, correct, explanation)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ch, q.get("topic", ""), q["question"].strip(),
                 opts["A"], opts["B"], opts["C"], opts["D"],
                 correct, q["explanation"].strip()),
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
        except (KeyError, TypeError) as e:
            bad += 1
    return ch, inserted, skipped, bad


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    files = sorted(glob.glob(os.path.join(JSON_DIR, "ch*.json")))
    if len(sys.argv) > 1:  # optional: load only specific files
        files = sys.argv[1:]
    total = 0
    for path in files:
        ch, ins, skip, bad = load_file(cur, path)
        conn.commit()
        total += ins
        print(f"Ch{ch:02d}: +{ins} inserted, {skip} dup, {bad} bad  ({os.path.basename(path)})")
    print(f"\nTotal newly inserted: {total}")
    cur.execute("SELECT COUNT(*) FROM questions")
    print(f"Total questions in DB: {cur.fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()

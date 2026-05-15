import sqlite3, json

c = sqlite3.connect('mcq.db')

# Tables
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("=== TABLES ===")
for t in tables:
    print(f"  - {t[0]}")

# Users
print("\n=== USERS ===")
users = c.execute("SELECT id, email, created_at FROM users").fetchall()
if users:
    for u in users:
        print(f"  id={u[0]}  email={u[1]}  created={u[2]}")
else:
    print("  (no users)")

# Questions summary
print("\n=== QUESTIONS SUMMARY ===")
total = c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
with_images = c.execute("SELECT COUNT(*) FROM questions WHERE images IS NOT NULL AND images != '[]'").fetchone()[0]
print(f"  Total questions : {total}")
print(f"  With images     : {with_images}")

topics = c.execute("SELECT topic, COUNT(*) as n FROM questions GROUP BY topic ORDER BY n DESC").fetchall()
print(f"\n  Questions per topic:")
for t in topics:
    print(f"    {t[1]:4d}  {t[0]}")

# Sessions summary
print("\n=== QUIZ SESSIONS ===")
sessions = c.execute("SELECT COUNT(*), COUNT(ended_at) FROM quiz_sessions").fetchone()
print(f"  Total sessions    : {sessions[0]}")
print(f"  Completed sessions: {sessions[1]}")

# Sample question
print("\n=== SAMPLE QUESTION (id=1) ===")
q = c.execute("SELECT id, topic, scenario, stem, opt_1, opt_2, opt_3, opt_4, opt_5, correct_opt, tagline FROM questions WHERE id=1").fetchone()
if q:
    keys = ['id','topic','scenario','stem','opt_1','opt_2','opt_3','opt_4','opt_5','correct_opt','tagline']
    for k, v in zip(keys, q):
        val = (str(v)[:120] + '...') if v and len(str(v)) > 120 else str(v)
        print(f"  {k:<12}: {val}")

c.close()

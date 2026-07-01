import sqlite3

conn = sqlite3.connect('data/agent.db')
rows = conn.execute(
    "SELECT role, substr(content, 1, 300) FROM messages "
    "WHERE session_id='25c33d97' "
    "ORDER BY created_at DESC LIMIT 6"
).fetchall()

for r in rows:
    print(f"{r[0]}: {r[1]}")
    print("---")
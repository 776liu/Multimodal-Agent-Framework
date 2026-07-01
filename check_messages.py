import sqlite3

conn = sqlite3.connect('data/agent.db')
rows = conn.execute(
    "SELECT session_id, role, substr(content, 1, 300) FROM messages "
    "ORDER BY created_at DESC LIMIT 10"
).fetchall()

for r in rows:
    print(f"session={r[0]}, role={r[1]}")
    print(f"content={r[2]}")
    print("---")

conn.close()
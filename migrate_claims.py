import sqlite3

conn = sqlite3.connect("civiclens.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE reports ADD COLUMN claimed_by TEXT")
    conn.commit()
    print("Added claimed_by column successfully!")
except sqlite3.OperationalError:
    print("claimed_by column already exists.")

try:
    cursor.execute("ALTER TABLE reports ADD COLUMN claimed_at TIMESTAMP")
    conn.commit()
    print("Added claimed_at column successfully!")
except sqlite3.OperationalError:
    print("claimed_at column already exists.")

conn.close()
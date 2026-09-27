import sqlite3

conn = sqlite3.connect("civiclens.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE reports ADD COLUMN user_phone TEXT DEFAULT 'Anonymous'")
    conn.commit()
    print("Added user_phone column successfully!")
except sqlite3.OperationalError:
    print("Column already exists.")

conn.close()
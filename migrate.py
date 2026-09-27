import sqlite3

conn = sqlite3.connect("civiclens.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE reports ADD COLUMN resolved_image_path TEXT")
    conn.commit()
    print("Added resolved_image_path column successfully!")
except sqlite3.OperationalError:
    print("Column already exists.")

conn.close()
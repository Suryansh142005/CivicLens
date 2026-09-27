import sqlite3

conn = sqlite3.connect("civiclens.db")
cursor = conn.cursor()

# 1. Create table with Date of Birth (dob) and no OTP fields
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        dob TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# 2. Check if the table already existed without 'dob' and add it safely
cursor.execute("PRAGMA table_info(users)")
existing_columns = [col[1] for col in cursor.fetchall()]

if "dob" not in existing_columns:
    cursor.execute("ALTER TABLE users ADD COLUMN dob TEXT")
    print("Added missing column: dob")

conn.commit()
conn.close()
print("Users table created/verified successfully with DOB support!")
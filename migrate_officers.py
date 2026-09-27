import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect("civiclens.db")
cursor = conn.cursor()

# 1. Create table with Date of Birth (dob) column
cursor.execute("""
    CREATE TABLE IF NOT EXISTS officers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        officer_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        dob TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

# 2. Check if table existed without 'dob' and add it safely
cursor.execute("PRAGMA table_info(officers)")
columns = [col[1] for col in cursor.fetchall()]
if "dob" not in columns:
    cursor.execute("ALTER TABLE officers ADD COLUMN dob TEXT DEFAULT '1990-01-01'")
    conn.commit()
    print("Added 'dob' column to officers table.")

# 3. Create index on department for fast filtering
cursor.execute("CREATE INDEX IF NOT EXISTS idx_officers_dept ON officers (department)")
conn.commit()
print("Officers table checked and verified successfully!")

# Seed starter officers with individual DOBs (YYYY-MM-DD)
starter_officers = [
    ("OFFICER101", "Officer 101", "Roads & Public Infrastructure", "1988-05-14", "admin123"),
    ("ADMIN01", "Officer Admin01", "Sanitation & Solid Waste Management", "1992-10-21", "admin123"),
    ("CORP2026", "Officer Corp2026", "Electrical & Street Lighting", "1985-03-30", "admin123"),
    ("WATER01", "Officer Water01", "Water Supply & Drainage Board", "1990-12-05", "admin123"),
]

for officer_id, name, department, dob, password in starter_officers:
    cursor.execute("SELECT id FROM officers WHERE officer_id = ?", (officer_id,))
    if cursor.fetchone():
        print(f"{officer_id} already exists, skipping.")
        continue
    hashed_pw = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO officers (officer_id, name, department, dob, password_hash) VALUES (?, ?, ?, ?, ?)",
        (officer_id, name, department, dob, hashed_pw)
    )
    print(f"Seeded {officer_id} ({department}) with DOB {dob}.")

conn.commit()
conn.close()
print("Done.")
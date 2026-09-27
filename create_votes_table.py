import sqlite3

conn = sqlite3.connect("civiclens.db")
cursor = conn.cursor()

# Composite UNIQUE constraint ensures a phone number can only vote once per report_id
cursor.execute("""
    CREATE TABLE IF NOT EXISTS report_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER NOT NULL,
        phone TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(report_id, phone),
        FOREIGN KEY(report_id) REFERENCES reports(id)
    )
""")

conn.commit()
conn.close()
print("Report votes tracking table created successfully!")
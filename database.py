import sqlite3

def init_db():
    conn = sqlite3.connect("civiclens.db")
    cursor = conn.cursor()

    # Enable SQLite foreign key constraint enforcement
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Main Reports Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            image_path TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            votes_count INTEGER DEFAULT 1,
            is_emergency INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Pending Verification',
            user_phone TEXT DEFAULT 'Anonymous',
            resolved_image_path TEXT,
            claimed_by TEXT,
            claimed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Additional Supporting Images for Merged Reports
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS report_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            image_path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE
        )
    """)

    # 3. Report Votes Table (Composite Unique constraint: 1 vote per phone per report)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS report_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            phone TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_id, phone),
            FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_votes_lookup 
        ON report_votes (report_id, phone)
    """)

    # 4. Users Table (Citizens with Date of Birth - No OTP fields)
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

    # 5. Officers Table (Municipal Staff)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS officers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            officer_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            dob TEXT,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_officers_dept 
        ON officers (department)
    """)

    # --- Safe schema upgrade checks for existing databases ---
    
    # Check reports table columns
    cursor.execute("PRAGMA table_info(reports)")
    report_columns = [col[1] for col in cursor.fetchall()]

    report_missing_cols = {
        "user_phone": "TEXT DEFAULT 'Anonymous'",
        "resolved_image_path": "TEXT",
        "claimed_by": "TEXT",
        "claimed_at": "TIMESTAMP"
    }
    for col_name, col_type in report_missing_cols.items():
        if col_name not in report_columns:
            cursor.execute(f"ALTER TABLE reports ADD COLUMN {col_name} {col_type}")
            print(f"Added column '{col_name}' to reports table.")

    # Check users table columns (ensure 'dob' exists)
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [col[1] for col in cursor.fetchall()]

    if "dob" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN dob TEXT")
        print("Added column 'dob' to users table.")

    # Check officers table columns (ensure 'dob' exists)
    cursor.execute("PRAGMA table_info(officers)")
    officer_columns = [col[1] for col in cursor.fetchall()]

    if "dob" not in officer_columns:
        cursor.execute("ALTER TABLE officers ADD COLUMN dob TEXT")
        print("Added column 'dob' to officers table.")

    conn.commit()
    conn.close()
    print("Database initialized and verified successfully!")

if __name__ == "__main__":
    init_db()
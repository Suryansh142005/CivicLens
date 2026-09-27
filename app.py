import os
import math
import sqlite3
import base64
import time
import requests
import requests as http_requests
import random

from dotenv import load_dotenv
load_dotenv(override=True)
print("KEY LOADED:", repr(os.environ.get("ASSEMBLYAI_API_KEY")))
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from flask import send_file
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from flask import Flask, render_template, request, jsonify
from flask import (Flask, flash, jsonify, redirect, render_template, request, session, url_for)
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "civiclens_secret_local_key_change_in_prod"
# Add this line right here:
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Auth Decorator to protect routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_phone" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function

# --- Access Control Decorator ---
def admin_required(f):

  @wraps(f)
  def decorated_function(*args, **kwargs):
    if not session.get("is_admin"):
      return redirect(url_for("admin_login"))
    return f(*args, **kwargs)

  return decorated_function

SUPERADMIN_ID = os.environ.get("SUPERADMIN_ID", "superadmin")
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "changeme123")

def superadmin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_superadmin"):
            return redirect(url_for("superadmin_login"))
        return f(*args, **kwargs)
    return decorated_function

def get_db_connection():
    conn = sqlite3.connect("civiclens.db")
    conn.row_factory = sqlite3.Row
    return conn

# Haversine formula to calculate distance in meters between two GPS coordinates
def calculate_distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000  # Radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# --- Rule-based classification for voice reports (no external LLM required) ---
EMERGENCY_KEYWORDS = [
    "fire", "burning", "flames", "live wire", "electrocut", "sparking",
    "collapse", "collapsed", "flooding", "flood", "explosion", "gas leak",
    "emergency", "danger", "dangerous", "urgent", "trapped", "injured", "injury"
]

CATEGORY_KEYWORDS = {
    "Road Damage": ["pothole", "road", "crack", "asphalt", "street damage", "sinkhole"],
    "Garbage / Waste": ["garbage", "trash", "waste", "litter", "dump", "rubbish"],
    "Broken Streetlight": ["streetlight", "street light", "lamp", "lighting", "dark street"],
    "Water Leakage": ["water leak", "pipe leak", "leaking", "burst pipe", "flooding water"],
    "Open Manhole": ["manhole", "open drain", "uncovered drain", "sewer opening"]
}

def classify_voice_report(transcript_text):
    text_lower = transcript_text.lower()

    is_emergency = any(keyword in text_lower for keyword in EMERGENCY_KEYWORDS)

    category = "Other"
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text_lower for keyword in keywords):
            category = cat
            break

    return category, is_emergency


@app.route("/api/submit-report", methods=["POST"])
def submit_report():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No data received"}), 400

    title = data.get("title")
    category = data.get("category")
    description = data.get("description", "")
    
    # Safe float parsing
    try:
        lat = float(data.get("latitude"))
        lon = float(data.get("longitude"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Valid latitude and longitude are required."}), 400

    # Accept either 'image' or 'image_data' key from frontend
    image_base64 = data.get("image") or data.get("image_data")
    is_emergency = 1 if data.get("is_emergency") else 0
    user_phone = session.get("user_phone", "Anonymous")

    if not title or not category or not image_base64:
        return jsonify({"success": False, "message": "Missing required fields or photo proof."}), 400

    # Ensure uploads directory exists
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # Save photo to static/uploads/
    if "," in image_base64:
        image_data = image_base64.split(",")[1]
    else:
        image_data = image_base64

    filename = f"report_{int(time.time())}.png"
    disk_filepath = os.path.join(UPLOAD_FOLDER, filename)
    web_filepath = f"/static/uploads/{filename}"

    with open(disk_filepath, "wb") as fh:
        fh.write(base64.b64decode(image_data))

    conn = get_db_connection()
    cursor = conn.cursor()

    # If it's an emergency, do not cluster; escalate directly
    if is_emergency:
        cursor.execute("""
            INSERT INTO reports (title, category, description, image_path, latitude, longitude, is_emergency, status, user_phone, votes_count)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'In Progress', ?, 1)
        """, (title, category, description, web_filepath, lat, lon, user_phone))
        conn.commit()
        conn.close()
        return jsonify({
            "success": True,
            "message": "🚨 Emergency reported! Escalated directly to In Progress without waiting for votes."
        })

    # --- CLUSTERING CHECK ---
    # Find all active complaints in the same category
    cursor.execute("SELECT id, latitude, longitude, votes_count FROM reports WHERE category = ? AND status != 'Resolved'", (category,))
    existing_reports = cursor.fetchall()

    matched_report = None
    for rep in existing_reports:
        dist = calculate_distance_meters(lat, lon, rep["latitude"], rep["longitude"])
        if dist <= 30.0:  # Within 30 meters threshold
            matched_report = rep
            break

    if matched_report:
        # 1. Update votes on the existing master ticket
        new_votes = (matched_report["votes_count"] or 0) + 1
        new_status = "In Progress" if new_votes >= 10 else "Pending Verification"

        cursor.execute("""
            UPDATE reports 
            SET votes_count = ?, status = ? 
            WHERE id = ?
        """, (new_votes, new_status, matched_report["id"]))

        # 2. Add this photo to the gallery of the master ticket (if table exists)
        try:
            cursor.execute("""
                INSERT INTO report_images (report_id, image_path)
                VALUES (?, ?)
            """, (matched_report["id"], web_filepath))
        except Exception:
            pass  # Fail gracefully if report_images table isn't created yet

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "merged": True,
            "report_id": matched_report["id"],
            "votes": new_votes,
            "message": f"Identical issue detected within 30m! Your photo was added and votes increased to {new_votes}/10."
        })

    # If no duplicate found, create a brand-new report with user_phone
    cursor.execute("""
        INSERT INTO reports (title, category, description, image_path, latitude, longitude, votes_count, is_emergency, status, user_phone)
        VALUES (?, ?, ?, ?, ?, ?, 1, 0, 'Pending Verification', ?)
    """, (title, category, description, web_filepath, lat, lon, user_phone))
    conn.commit()
    report_id = cursor.lastrowid
    conn.close()

    return jsonify({
        "success": True,
        "merged": False,
        "report_id": report_id,
        "votes": 1,
        "message": "New complaint registered! It is now visible to nearby citizens for verification."
    })

# 1. Route to serve the Map & Feed page
@app.route("/feed")
def feed():
    return render_template("index.html")

# 2. API to fetch reports within 3 km of the user
@app.route("/api/nearby-reports", methods=["GET"])
def get_nearby_reports():
    user_lat = request.args.get("lat", type=float)
    user_lon = request.args.get("lon", type=float)

    if user_lat is None or user_lon is None:
        return jsonify({"error": "Latitude and longitude required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY created_at DESC")
    all_reports = cursor.fetchall()
    conn.close()

    nearby = []
    for r in all_reports:
        dist_meters = calculate_distance_meters(user_lat, user_lon, r["latitude"], r["longitude"])
        dist_km = dist_meters / 1000.0

        if dist_km <= 3.0 or r["is_emergency"] == 1:
            # --- ADD IT RIGHT HERE ---
            resolved_img = r["resolved_image_path"].replace("\\", "/") if r["resolved_image_path"] else None

            nearby.append({
                "id": r["id"],
                "title": r["title"],
                "category": r["category"],
                "description": r["description"],
                "image_path": r["image_path"].replace("\\", "/"),
                "resolved_image_path": resolved_img,
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "votes_count": r["votes_count"],
                "is_emergency": bool(r["is_emergency"]),
                "status": r["status"],
                "distance_km": round(dist_km, 2)
            })
            # -------------------------

    return jsonify(nearby)

# 1. Reverse Geocoding helper to extract city/district from coordinates
def get_city_from_coordinates(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        headers = {"User-Agent": "CivicLens-GrievanceDispatcher/1.0"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            address = res.json().get("address", {})
            # Look for city, town, or district
            city = address.get("city") or address.get("state_district") or address.get("county") or "Unknown"
            return city
    except Exception as e:
        print(f"[Reverse Geocoding Error]: {e}")
    return "Unknown"

# 2. Municipal Authority Registry & API Adapter
MUNICIPAL_DIRECTORY = {
    "Kanpur": {
        "portal_name": "Kanpur Nagar Nigam (KNN) Citizen Grievance Redressal",
        "api_endpoint": "https://api.kanpurnagarnigam.in/v1/grievance/register", # simulated / live endpoint
        "categories": {
            "Road Damage": "Public Works Department (PWD / Nagar Nigam)",
            "Garbage / Waste": "Health & Sanitation Wing, KNN",
            "Broken Streetlight": "Electrical & Lighting Department, KNN",
            "Water Leakage": "Kanpur Jal Sansthan",
            "Open Manhole": "Sewerage & Drainage Board, KNN"
        }
    },
    "Lucknow": {
        "portal_name": "Lucknow Municipal Corporation (LMC)",
        "api_endpoint": "https://api.lmc.up.nic.in/v1/grievance/register",
        "categories": {
            "Road Damage": "LMC Civil Maintenance",
            "Garbage / Waste": "LMC Sanitation Division",
            "Broken Streetlight": "LMC Streetlighting Division",
            "Water Leakage": "Lucknow Jal Sansthan",
            "Open Manhole": "LMC Sewerage Cell"
        }
    }
}

# 3. Automated External Dispatcher
def auto_dispatch_to_government_portal(report_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE reports SET status = 'In Progress' WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    
    cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    report = cursor.fetchone()
    if not report:
        conn.close()
        return

    # Determine city from report coordinates
    city_detected = get_city_from_coordinates(report["latitude"], report["longitude"])
    
    # Check if city has a registered municipal authority
    matched_municipality = None
    for city_key in MUNICIPAL_DIRECTORY:
        if city_key.lower() in city_detected.lower():
            matched_municipality = MUNICIPAL_DIRECTORY[city_key]
            break

    # Fallback to general district portal if city not specifically mapped
    if not matched_municipality:
        target_portal = f"District Grievance Redressal Cell ({city_detected})"
        target_dept = "Municipal Administration Department"
        api_url = "https://jansunwai.up.nic.in/api/v1/grievance"  # Integrated Grievance Redressal System (IGRS)
    else:
        target_portal = matched_municipality["portal_name"]
        target_dept = matched_municipality["categories"].get(report["category"], "General Municipal Services")
        api_url = matched_municipality["api_endpoint"]

    # Construct the formal dispatch payload
    external_payload = {
        "external_reference_id": f"CL-REP-{report['id']}",
        "city": city_detected,
        "department": target_dept,
        "category": report["category"],
        "title": report["title"],
        "description": report["description"],
        "latitude": report["latitude"],
        "longitude": report["longitude"],
        "public_votes": report["votes_count"],
        "is_emergency": bool(report["is_emergency"]),
        "status": "Escalated to Field Office"
    }

    print(f"\n============================================================")
    print(f"🚨 [AUTO-DISPATCH TRIGGERED: 10 VOTES REACHED]")
    print(f"Target City: {city_detected}")
    print(f"Target Portal: {target_portal}")
    print(f"Designated Department: {target_dept}")
    print(f"Payload Transmitted: {external_payload}")
    print(f"============================================================\n")

    # Mark the report as officially escalated in your local database
    cursor.execute("""
        UPDATE reports 
        SET status = 'Escalated to Municipality', 
            description = description || ' [AUTO-ROUTED to ' || ? || ' - ' || ? || ']'
        WHERE id = ?
    """, (target_portal, target_dept, report_id))
    
    conn.commit()
    conn.close()

# 3. API to handle 1-click verification votes
@app.route("/api/vote/<int:report_id>", methods=["POST"])
def vote_report(report_id):
    # 1. Identify voter phone
    user_phone = session.get("user_phone")

    if not user_phone:
        return jsonify({
            "success": False, 
            "message": "Please log in to verify and upvote this issue."
        }), 401

    conn = get_db_connection()
    cursor = conn.cursor()

    # 2. Check if the logged-in user is the original creator of this report
    cursor.execute("SELECT user_phone, votes_count, status FROM reports WHERE id = ?", (report_id,))
    report = cursor.fetchone()

    if not report:
        conn.close()
        return jsonify({"success": False, "message": "Report not found."}), 404

    if report["user_phone"] == user_phone:
        conn.close()
        return jsonify({
            "success": False,
            "message": "You cannot vote on your own reported issue."
        }), 403

    # 3. Check if this phone number has already voted on this report
    cursor.execute("SELECT id FROM report_votes WHERE report_id = ? AND phone = ?", (report_id, user_phone))
    existing_vote = cursor.fetchone()

    if existing_vote:
        conn.close()
        return jsonify({
            "success": False, 
            "message": "You have already verified/upvoted this complaint."
        }), 400

    # 4. Record the vote and calculate new count
    new_votes = (report["votes_count"] or 0) + 1
    escalated = False

    cursor.execute("INSERT INTO report_votes (report_id, phone) VALUES (?, ?)", (report_id, user_phone))

    # 5. Escalate status directly to 'In Progress' when 10 votes are hit
    if new_votes >= 10 and report["status"] != "Resolved":
        cursor.execute(
            "UPDATE reports SET status = 'In Progress', votes_count = ? WHERE id = ?",
            (new_votes, report_id)
        )
        escalated = True
    else:
        cursor.execute(
            "UPDATE reports SET votes_count = ? WHERE id = ?",
            (new_votes, report_id)
        )

    conn.commit()

    # 6. Optional auto-dispatch trigger on the 10th vote
    if escalated and new_votes == 10:
        auto_dispatch_to_government_portal(report_id)

    # 7. Fetch final committed status
    cursor.execute("SELECT status FROM reports WHERE id = ?", (report_id,))
    final_status = cursor.fetchone()["status"]
    conn.close()

    return jsonify({
        "success": True, 
        "new_votes": new_votes, 
        "escalated": escalated,
        "status": final_status,
        "message": "Vote recorded successfully!"
    })

@app.route("/download-docket/<int:report_id>")
def download_docket(report_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    report = cursor.fetchone()
    conn.close()

    if not report:
        return "Report not found", 404

    # Create an in-memory PDF buffer
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # --- Header Banner ---
    p.setFillColor(colors.HexColor("#1e293b"))
    p.rect(0, height - 75, width, 75, fill=1, stroke=0)
    
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 20)
    p.drawString(40, height - 42, "CivicLens Municipal Escalation Docket")
    p.setFont("Helvetica", 10)
    p.drawString(40, height - 60, "Official Pre-Triage Evidence Package for Municipal Action")

    # --- Verification Badge ---
    if report["is_emergency"]:
        p.setFillColor(colors.HexColor("#dc2626"))
        badge_text = "CRITICAL: DIRECT EMERGENCY DISPATCH"
    elif report["votes_count"] >= 10:
        p.setFillColor(colors.HexColor("#16a34a"))
        badge_text = "STATUS: COMMUNITY VERIFIED (10/10 CONSENSUS)"
    else:
        p.setFillColor(colors.HexColor("#ca8a04"))
        badge_text = f"STATUS: PENDING VERIFICATION ({report['votes_count']}/10 VOTES)"

    p.roundRect(40, height - 115, 530, 26, 4, fill=1, stroke=0)
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 11)
    p.drawCentredString(width / 2.0, height - 107, badge_text)

    # --- Ticket Details Box ---
    p.setFillColor(colors.HexColor("#0f172a"))
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, height - 145, f"Ticket ID: #CL-2026-{report['id']}")

    p.setFont("Helvetica", 10)
    p.setFillColor(colors.HexColor("#334155"))
    p.drawString(40, height - 165, f"Category: {report['category']}")
    p.drawString(40, height - 180, f"Report Title: {report['title']}")
    p.drawString(40, height - 195, f"Timestamp: {report['created_at']}")
    p.drawString(40, height - 210, f"GPS Coordinates: {report['latitude']:.5f}, {report['longitude']:.5f}")
    
    maps_link = f"https://www.google.com/maps?q={report['latitude']},{report['longitude']}"
    p.setFillColor(colors.HexColor("#2563eb"))
    p.drawString(40, height - 225, f"Google Maps Pin: {maps_link}")

    p.setFillColor(colors.HexColor("#334155"))
    p.drawString(40, height - 245, f"Citizen Notes: {report['description'] or 'No additional notes provided.'}")

    # --- Live Captured Photo ---
    image_fs_path = report["image_path"].lstrip("/")
    if os.path.exists(image_fs_path):
        p.drawString(40, height - 275, "Field Verification Photograph (Live Hardware Capture):")
        try:
            img = ImageReader(image_fs_path)
            p.drawImage(img, 40, height - 560, width=380, height=270, preserveAspectRatio=True)
        except Exception:
            p.drawString(40, height - 300, "[Image Render Error]")

    # --- Footer Sign-off ---
    p.setStrokeColor(colors.HexColor("#cbd5e1"))
    p.line(40, 60, width - 40, 60)
    p.setFillColor(colors.HexColor("#64748b"))
    p.setFont("Helvetica-Oblique", 8)
    p.drawString(40, 45, "Generated automatically by CivicLens Platform. Authenticated via hardware geolocation and proximity quorum.")

    p.showPage()
    p.save()

    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"CivicLens_Docket_{report['id']}.pdf", mimetype="application/pdf")


# 2. API to Update Status (e.g., 'In Progress', 'Resolved')
@app.route("/api/admin/update-status/<int:report_id>", methods=["POST"])
@admin_required
def update_status(report_id):
    data = request.get_json()
    new_status = data.get("status")
    resolved_img_base64 = data.get("resolved_image")

    if not new_status:
        return jsonify({"success": False, "message": "Status is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    resolved_path = None
    if new_status == "Resolved" and resolved_img_base64:
        image_data = resolved_img_base64.split(",")[1]
        filename = f"resolved_{report_id}_{int(time.time())}.png"
        resolved_path = os.path.join(UPLOAD_FOLDER, filename)
        with open(resolved_path, "wb") as fh:
            fh.write(base64.b64decode(image_data))

    if resolved_path:
        cursor.execute("""
            UPDATE reports 
            SET status = ?, resolved_image_path = ? 
            WHERE id = ?
        """, (new_status, resolved_path, report_id))
    else:
        cursor.execute("UPDATE reports SET status = ? WHERE id = ?", (new_status, report_id))

    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Status updated to '{new_status}'"})

# Route to render the My Reports page
@app.route("/my-reports")
def my_reports_page():
    return render_template("my_reports.html")

# API to fetch reports submitted by the logged-in user only
@app.route("/api/my-reports", methods=["GET"])
@login_required
def get_user_reports():
    phone = session.get("user_phone")
    if not phone:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE user_phone = ? ORDER BY created_at DESC", (phone,))
    reports = cursor.fetchall()
    conn.close()

    result = []
    for r in reports:
        resolved_img = r["resolved_image_path"].replace("\\", "/") if r["resolved_image_path"] else None
        result.append({
            "id": r["id"],
            "title": r["title"],
            "category": r["category"],
            "description": r["description"],
            "image_path": r["image_path"].replace("\\", "/"),
            "resolved_image_path": resolved_img,
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "votes_count": r["votes_count"],
            "status": r["status"],
            "created_at": r["created_at"]
        })

    return jsonify(result)

# Protect the report submission page
@app.route("/")
@login_required
def home():
    return render_template("report.html", user_name=session.get("user_name"), user_phone=session.get("user_phone"))

# Login / Register View (handles both 'login' and 'login_page' endpoints)
@app.route("/login", endpoint="login_page")
def login_page():
    if "user_phone" in session:
        return redirect(url_for("home"))
    return render_template("login.html")

# Register API
@app.route("/api/register", methods=["POST"])
def register_user():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    dob = data.get("dob", "").strip()  # Format: YYYY-MM-DD
    password = data.get("password", "")

    if not name or not phone or not dob or not password:
        return jsonify({"success": False, "message": "All fields including Date of Birth are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Phone number already registered. Please login."}), 409

    hashed_pw = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO users (name, phone, dob, password_hash) VALUES (?, ?, ?, ?)",
        (name, phone, dob, hashed_pw)
    )
    conn.commit()
    conn.close()

    session["user_phone"] = phone
    session["user_name"] = name
    return jsonify({"success": True, "message": "Account created successfully!"})

# Login API
@app.route("/api/login", methods=["POST"])
def login_user():
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    password = data.get("password", "")

    if not phone or not password:
        return jsonify({"success": False, "message": "Phone and password are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, phone, password_hash FROM users WHERE phone = ?", (phone,))
    user = cursor.fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"success": False, "message": "Invalid phone number or password"}), 401

    session["user_phone"] = user["phone"]
    session["user_name"] = user["name"]
    return jsonify({"success": True, "message": "Login successful!"})

@app.route("/forgot-password")
def forgot_password_page():
    return render_template("forgot_password.html")

@app.route("/api/forgot-password/reset", methods=["POST"])
def reset_password_with_dob():
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    dob = data.get("dob", "").strip()
    new_password = data.get("new_password", "")

    if not phone or not dob or not new_password:
        return jsonify({"success": False, "message": "Phone number, Date of Birth, and new password are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE phone = ? AND dob = ?", (phone, dob))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({"success": False, "message": "No account found matching this Phone Number and Date of Birth."}), 404

    hashed_pw = generate_password_hash(new_password)
    cursor.execute("UPDATE users SET password_hash = ? WHERE phone = ?", (hashed_pw, phone))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Password reset successfully! Redirecting to login..."})


# --- 1. Municipal Officer Login & Logout ---
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
  if request.method == "POST":
    officer_id = request.form.get("officer_id", "").strip()
    password = request.form.get("password", "").strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM officers WHERE officer_id = ?", (officer_id,))
    officer = cursor.fetchone()
    conn.close()

    if officer and check_password_hash(officer["password_hash"], password):
      session["is_admin"] = True
      session["officer_id"] = officer["officer_id"]
      session["department"] = officer["department"]
      return redirect(url_for("admin_dashboard"))
    else:
      return render_template(
          "admin_login.html", error="Invalid Officer ID or Access Key."
      )

  return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
  session.pop("is_admin", None)
  session.pop("officer_id", None)
  session.pop("department", None)
  return redirect(url_for("admin_login"))


# --- Super Admin: provisions officer accounts (not publicly accessible) ---
@app.route("/superadmin/login", methods=["GET", "POST"])
def superadmin_login():
  if request.method == "POST":
    admin_id = request.form.get("admin_id", "").strip()
    password = request.form.get("password", "").strip()

    if admin_id == SUPERADMIN_ID and password == SUPERADMIN_PASSWORD:
      session["is_superadmin"] = True
      return redirect(url_for("superadmin_officers"))
    else:
      return render_template("superadmin_login.html", error="Invalid credentials.")

  return render_template("superadmin_login.html")


@app.route("/superadmin/logout")
def superadmin_logout():
  session.pop("is_superadmin", None)
  return redirect(url_for("superadmin_login"))


@app.route("/superadmin/officers", methods=["GET", "POST"])
@superadmin_required
def superadmin_officers():
    conn = get_db_connection()
    cursor = conn.cursor()
    message = None
    error = None

    if request.method == "POST":
        officer_id = request.form.get("officer_id", "").strip().upper()
        name = request.form.get("name", "").strip()
        department = request.form.get("department", "").strip()
        dob = request.form.get("dob", "").strip()
        password = request.form.get("password", "").strip()

        if not officer_id or not name or not department or not dob or not password:
            error = "All fields, including Date of Birth, are required."
        else:
            cursor.execute("SELECT id FROM officers WHERE officer_id = ?", (officer_id,))
            if cursor.fetchone():
                error = f"Officer ID '{officer_id}' already exists."
            else:
                hashed_pw = generate_password_hash(password)
                cursor.execute(
                    "INSERT INTO officers (officer_id, name, department, dob, password_hash) VALUES (?, ?, ?, ?, ?)",
                    (officer_id, name, department, dob, hashed_pw)
                )
                conn.commit()
                message = f"Officer '{officer_id}' ({name}) created successfully."

    cursor.execute("SELECT officer_id, name, department, dob, created_at FROM officers ORDER BY department, officer_id")
    officers = cursor.fetchall()
    conn.close()

    return render_template(
        "superadmin_officers.html",
        officers=officers,
        message=message,
        error=error,
        departments=list(DEPARTMENT_CATEGORY_MAP.keys())
    )

@app.route("/admin/forgot-password")
def admin_forgot_password_page():
    return render_template("admin_forgot_password.html")

@app.route("/api/admin/forgot-password/reset", methods=["POST"])
def admin_reset_password_with_dob():
    data = request.get_json() or {}
    officer_id = data.get("officer_id", "").strip().upper()
    dob = data.get("dob", "").strip()
    new_password = data.get("new_password", "")

    if not officer_id or not dob or not new_password:
        return jsonify({"success": False, "message": "Officer ID, Date of Birth, and new password are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM officers WHERE officer_id = ? AND dob = ?", (officer_id, dob))
    officer = cursor.fetchone()

    if not officer:
        conn.close()
        return jsonify({"success": False, "message": "No matching officer found with this Badge ID and Date of Birth."}), 404

    hashed_pw = generate_password_hash(new_password)
    cursor.execute("UPDATE officers SET password_hash = ? WHERE officer_id = ?", (hashed_pw, officer_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Officer access key updated successfully! Redirecting to sign in..."})

# --- Department -> Category visibility mapping ---
DEPARTMENT_CATEGORY_MAP = {
    "Roads & Public Infrastructure": ["Road Damage", "Other"],
    "Sanitation & Solid Waste Management": ["Garbage / Waste"],
    "Electrical & Street Lighting": ["Broken Streetlight"],
    "Water Supply & Drainage Board": ["Water Leakage", "Open Manhole"]
}

# --- 2. Municipal Admin Dashboard ---
@app.route("/admin")
@admin_required
def admin_dashboard():
  conn = get_db_connection()
  cursor = conn.cursor()

  department = session.get("department")
  allowed_categories = DEPARTMENT_CATEGORY_MAP.get(department, [])

  if allowed_categories:
    placeholders = ",".join("?" for _ in allowed_categories)
    category_clause = f"(is_emergency = 1 OR category IN ({placeholders}))"
    params = list(allowed_categories)
  else:
    # Unknown/unmapped department: only emergencies are visible
    category_clause = "is_emergency = 1"
    params = []

  query = f"""
        SELECT * FROM reports
        WHERE (is_emergency = 1 OR votes_count >= 10 OR status = 'Resolved')
          AND {category_clause}
        ORDER BY
            CASE
                WHEN status = 'Resolved' THEN 3
                WHEN is_emergency = 1 THEN 1
                WHEN votes_count >= 10 THEN 2
                ELSE 4
            END,
            id DESC
    """
  cursor.execute(query, params)
  reports = cursor.fetchall()
  conn.close()

  return render_template(
      "admin.html",
      reports=reports,
      officer_id=session.get("officer_id"),
      department=session.get("department"),
  )

# --- Claim a ticket so only this officer can resolve it ---
@app.route("/admin/claim/<int:report_id>", methods=["POST"])
@admin_required
def claim_report(report_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT claimed_by, status FROM reports WHERE id = ?", (report_id,))
    report = cursor.fetchone()

    if not report:
        conn.close()
        return jsonify({"success": False, "message": "Report not found."}), 404

    if report["status"] == "Resolved":
        conn.close()
        return jsonify({"success": False, "message": "This ticket is already resolved."}), 400

    if report["claimed_by"] and report["claimed_by"] != session.get("officer_id"):
        conn.close()
        return jsonify({
            "success": False,
            "message": f"This ticket is already being handled by {report['claimed_by']}."
        }), 409

    cursor.execute(
        "UPDATE reports SET claimed_by = ?, claimed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session.get("officer_id"), report_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Ticket claimed. You can now resolve it."})

# --- 3. Resolve Grievance with Resolution Image Proof ---
@app.route("/admin/resolve/<int:report_id>", methods=["POST"])
@admin_required
def resolve_report(report_id):
  conn_check = get_db_connection()
  cursor_check = conn_check.cursor()
  cursor_check.execute("SELECT claimed_by FROM reports WHERE id = ?", (report_id,))
  claim_row = cursor_check.fetchone()
  conn_check.close()

  if not claim_row or claim_row["claimed_by"] != session.get("officer_id"):
    return jsonify({
        "success": False,
        "message": "You must claim this ticket before resolving it."
    }), 403

  if "resolution_image" not in request.files:
    return (
        jsonify({
            "success": False,
            "message": "Physical verification photo is mandatory.",
        }),
        400,
    )

  file = request.files["resolution_image"]
  resolution_notes = request.form.get("notes", "Work completed and verified.")

  if file.filename == "":
    return (
        jsonify({
            "success": False,
            "message": "No file selected for resolution proof.",
        }),
        400,
    )

  if file:
    filename = secure_filename(f"resolved_{report_id}_{file.filename}")
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)
    web_accessible_path = f"/static/uploads/{filename}"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
            UPDATE reports 
            SET status = 'Resolved', 
                resolved_image_path = ?
            WHERE id = ?
        """,
        (web_accessible_path, report_id),
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Report #{report_id} has been marked as Resolved with photo evidence.",
    })

ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY")
ASSEMBLYAI_BASE = "https://api.assemblyai.com"

@app.route("/api/voice-process", methods=["POST"])
@login_required
def voice_process():
    if "audio" not in request.files:
        return jsonify({"success": False, "message": "No audio file received."}), 400

    audio_file = request.files["audio"]
    headers = {"authorization": ASSEMBLYAI_API_KEY}

    # 1. Upload raw audio bytes to AssemblyAI
    upload_res = requests.post(
        f"{ASSEMBLYAI_BASE}/v2/upload",
        headers=headers,
        data=audio_file.read()
    )
    if upload_res.status_code != 200:
        print("AssemblyAI upload error:", upload_res.status_code, upload_res.text)
        return jsonify({"success": False, "message": f"Audio upload failed: {upload_res.text}"}), 502
    upload_url = upload_res.json()["upload_url"]

    # 2. Submit for transcription
    transcript_res = requests.post(
        f"{ASSEMBLYAI_BASE}/v2/transcript",
        headers=headers,
        json={"audio_url": upload_url}
    )
    transcript_id = transcript_res.json()["id"]

    # 3. Poll until done
    polling_url = f"{ASSEMBLYAI_BASE}/v2/transcript/{transcript_id}"
    for _ in range(60):  # ~60s max wait
        poll_res = requests.get(polling_url, headers=headers).json()
        if poll_res["status"] == "completed":
            break
        elif poll_res["status"] == "error":
            return jsonify({"success": False, "message": f"Transcription failed: {poll_res.get('error')}"}), 502
        time.sleep(2)
    else:
        return jsonify({"success": False, "message": "Transcription timed out."}), 504

    transcript_text = poll_res["text"]

    # 4. Rule-based classification (category + emergency flag) — no external LLM needed
    category, is_emergency = classify_voice_report(transcript_text)

    # Build a short title from the transcript (first ~8 words)
    words = transcript_text.strip().split()
    title = " ".join(words[:8]) + ("..." if len(words) > 8 else "")
    if not title:
        title = "Voice-reported issue"

    return jsonify({
        "success": True,
        "transcript": transcript_text,
        "title": title,
        "description": transcript_text,
        "category": category,
        "is_emergency": is_emergency
    })

    
# Logout Route
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
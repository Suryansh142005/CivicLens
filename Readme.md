# CivicLens

**An intelligent, hardware-verified, voice-powered civic grievance reporting and municipal tracking platform.**

Built for the [AssemblyAI Voice Agent Hackathon](https://lablab.ai) (lablab.ai × AssemblyAI, September 2026).

---

## The Problem

Traditional municipal grievance systems are broken: fake or downloaded photos, duplicate ticket clutter, no accountability, and no way for non-tech-savvy or elderly citizens to participate. CivicLens fixes this with a tamper-proof reporting pipeline, community-driven verification, an AI voice agent for hands-free reporting, and a real department-routed workflow for the municipal officers who resolve these tickets.

---

## Core Features

### Citizen side
- **Hardware-verified photo capture** — live camera only (`getUserMedia`), gallery uploads are disabled entirely to prevent fake/reused images
- **GPS telemetry lock** — high-accuracy coordinates captured at submission time
- **AI Voice Agent (CivicVoice)** — powered by **AssemblyAI**. Citizens can speak their complaint naturally; audio is transcribed via AssemblyAI's speech-to-text API, then parsed with rule-based NLU to extract a title, category, and emergency flag, auto-filling the report form
- **Emergency detection** — keyword-based detection (fire, live wire, flooding, etc.) bypasses community voting and escalates a ticket to "In Progress" immediately
- **Spatial deduplication** — new reports within 30 meters of an existing unresolved ticket in the same category are automatically merged, incrementing a shared vote count instead of creating clutter
- **Community verification** — one vote per citizen per ticket (enforced at both the application layer and the database layer via a `UNIQUE` constraint); reaching 10 votes marks a ticket **Community Verified**
- **Live community feed & map** (Leaflet + OpenStreetMap) with category/status filters and before/after resolution photos
- **Personal tracking dashboard** ("My Reports") with a visual progress stepper
- **Official PDF escalation docket** generated per ticket (ReportLab), including the live-captured proof photo and GPS pin
- **DOB-based password recovery** (phone number + date of birth)

### Officer side
- **Department-routed dashboard** — an officer only sees tickets from their own department's categories, plus **every** emergency regardless of category (safety issues are never hidden)
- **Visibility rules** — a non-emergency ticket only becomes visible to officers once it reaches 10 votes (Community Verified); emergencies and resolved tickets are always visible; sorting always puts emergencies first, then verified, then resolved last
- **Claim system** — an officer must claim a ticket ("Start Working") before resolving it; other officers in the same department see it locked ("🔒 Being handled by OFFICER101") and the backend rejects any resolve attempt from a non-claiming officer
- **Live-camera resolution proof** — officers must capture a live "after" photo through the browser to resolve a ticket; file uploads are disabled here too, closing the same fraud vector on the officer side
- **DOB-based password recovery** (Officer ID + date of birth)

### Administration
- **Super Admin panel** (`/superadmin/login`) — a separate, credential-gated tool (not linked anywhere in the public UI) used to provision officer accounts: Officer ID, name, one department, date of birth, and a temporary password. Officers cannot self-register.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask |
| Database | SQLite |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Maps | Leaflet.js + OpenStreetMap |
| Voice / Speech-to-Text | **AssemblyAI** (`/v2/upload`, `/v2/transcript`) |
| PDF generation | ReportLab |
| Auth | Werkzeug password hashing (`generate_password_hash` / `check_password_hash`) |
| Browser APIs | `getUserMedia` (camera), `MediaRecorder` (voice), `Geolocation` |

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd CivicLens
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a file named `.env` in the project root:

```
ASSEMBLYAI_API_KEY=your_assemblyai_api_key
SUPERADMIN_ID=choose_your_own_id
SUPERADMIN_PASSWORD=choose_a_strong_password
```

- Get a free AssemblyAI API key at [assemblyai.com](https://www.assemblyai.com) (the hackathon's signup link gives free credits).
- `SUPERADMIN_ID` / `SUPERADMIN_PASSWORD` are your credentials for the officer-provisioning panel — choose your own values, don't leave the code defaults in place.

### 3. Initialize the database

```bash
python database.py
python migrate_officers.py
```

`database.py` creates the full schema (reports, votes, users, officers) and safely upgrades an existing database if columns are missing. `migrate_officers.py` seeds four starter officer accounts (one per department) so you can log in and test immediately:

| Officer ID | Department | Password |
|---|---|---|
| OFFICER101 | Roads & Public Infrastructure | admin123 |
| ADMIN01 | Sanitation & Solid Waste Management | admin123 |
| CORP2026 | Electrical & Street Lighting | admin123 |
| WATER01 | Water Supply & Drainage Board | admin123 |

**Change these passwords (or create fresh accounts via the Super Admin panel and delete these) before any real deployment.**

### 4. Run the app

```bash
python app.py
```

Visit `http://127.0.0.1:5000`.

- **Citizen portal:** `/login`
- **Officer portal:** `/admin/login`
- **Super Admin (officer provisioning):** `/superadmin/login`
- **Public feed/map (no login required):** `/feed`

---

## Application Routes

| Route | Purpose |
|---|---|
| `GET /` | Report submission page (citizen, login required) |
| `GET /feed` | Public community feed & map |
| `GET /my-reports` | Citizen's personal report history |
| `POST /api/submit-report` | Submit a new grievance (camera-based) |
| `POST /api/voice-process` | Voice report: audio → AssemblyAI transcription → classification |
| `POST /api/vote/<id>` | Cast a verification vote on a ticket |
| `GET /download-docket/<id>` | Generate and download the official PDF docket |
| `GET /admin` | Officer dashboard (department-filtered) |
| `POST /admin/claim/<id>` | Claim a ticket for resolution |
| `POST /admin/resolve/<id>` | Resolve a claimed ticket with a live photo |
| `GET /superadmin/officers` | Super Admin: create/view officer accounts |

---

## Known Simplifications (by design, for this hackathon scope)

These are deliberate scope decisions, documented here for transparency rather than left as unexplained gaps:

- **Voice classification is rule-based (keyword matching)**, not LLM-based. AssemblyAI's LLM Gateway (used for the original LeMUR-based design) requires a paid account tier; the keyword-based fallback keeps the full pipeline free to run while still correctly classifying category and emergency status in testing. Swapping in an LLM-based classifier later is a drop-in replacement for `classify_voice_report()` in `app.py`.
- **Department → category routing is a hardcoded mapping** (`DEPARTMENT_CATEGORY_MAP` in `app.py`), not a configurable admin setting. Fine for four fixed departments; a production version would make this editable from the Super Admin panel.
- **Super Admin uses a single shared credential** (from `.env`), not individual per-person accounts with audit logging. Reasonable for a small team provisioning officers; a full production system would use proper multi-user admin accounts.
- **No email or SMS is sent anywhere** — password recovery for both citizens and officers uses phone/Officer ID + date of birth verification instead, to avoid any paid third-party dependency (SMS gateways cost money per message with no universal free tier; DOB-based recovery has no such cost and no delivery-reliability risk for a demo).

---

## Project Structure

```
CivicLens/
├── app.py                    # Main Flask application
├── database.py                # Consolidated schema creation + safe upgrades
├── migrate_officers.py        # Seeds starter officer accounts
├── create_users_db.py         # (legacy, superseded by database.py)
├── create_votes_table.py      # (legacy, superseded by database.py)
├── civiclens.db                # SQLite database (created on first run)
├── static/
│   ├── css/style.css
│   ├── js/main.js
│   └── uploads/                # Citizen & officer captured photos
└── templates/
    ├── login.html               # Citizen sign in / registration
    ├── report.html              # Camera + voice grievance reporting
    ├── index.html                # Public community feed & map
    ├── my_reports.html           # Citizen's personal report tracking
    ├── forgot_password.html      # Citizen password recovery
    ├── admin_login.html          # Officer sign in
    ├── admin.html                 # Officer dashboard
    ├── admin_forgot_password.html # Officer password recovery
    ├── superadmin_login.html      # Super Admin sign in
    └── superadmin_officers.html   # Officer account provisioning
```

---

## Built With

CivicLens was built for the AssemblyAI Voice Agent Hackathon, hosted by [lablab.ai](https://lablab.ai) and [AssemblyAI](https://www.assemblyai.com).
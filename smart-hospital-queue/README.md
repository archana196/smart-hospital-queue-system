# Smart Hospital Queue Management System

A web-based outpatient department (OPD) hospital queue management system built for Computer Science Engineering college project.

---

## Architecture Overview

```
+---------------------------------------------------------------------------------------+
|                                   CLIENT LAYER                                        |
|  [ Patient UI ]       [ QR Check-In Scanner ]    [ Doctor Dashboard ]   [ IoT Display ] |
| (Online/Walk-in)        (Token UUID verify)      (Call Next/Consult)     (Token/Room)   |
+---------------------------------------------------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                                 FLASK APP LAYER                                       |
|  - Auth & RBAC Routes         - Patient & Token Routes       - Doctor & Admin Routes  |
|                                                                                       |
|  +-------------------------------------+   +---------------------------------------+  |
|  |       QUEUE ENGINE (DECISION)       |   |       ML Predictor (ESTIMATION ONLY)  |  |
|  | - Priority: Emergency/High/Med/Norm |   | - Features: Queue len, available drs, |  |
|  | - Aging Mechanism (Anti-Starve)    |   |   priority, avg consult time, dept    |  |
|  | - Tie-Breaker: created_at timestamp |   | - Model: Random Forest Regressor      |  |
|  +-------------------------------------+   +---------------------------------------+  |
+---------------------------------------------------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                                  DATA & QR LAYER                                      |
|  - SQLite (Dev) / PostgreSQL (Prod) via SQLAlchemy ORM                                |
|  - Secure Non-PII QR Tokens (UUID4 hash lookup with anti-duplicate scan check)         |
+---------------------------------------------------------------------------------------+
```

---

## Key Features Implemented (Phase 1)

1. **Patient Registration System**:
   - Supports both **Walk-in** and **Online Appointment** registrations.
   - Requires **Appointment Date & Time** for Online registration; keeps them optional/NULL for Walk-in.
   - Captures triage priority (`Normal`, `Medium`, `High`, `Emergency`).

2. **Sequential Token Generation**:
   - Generates departmental tokens in the format `[DEPT_CODE]-[YYYYMMDD]-[SEQ]` (e.g. `GEN-20261008-001`).

3. **Secure Non-PII QR Design**:
   - Encodes **ONLY** a secure random UUID token reference (`qr_sec_...`) into SVG QR graphics.
   - **Zero Patient PII** (Name, Phone, Age, Gender) inside QR code payloads.

4. **Queue Engine Foundation**:
   - Calculates dynamic priority score with fairness aging (+10 points every 15 mins) to prevent normal priority starvation.
   - Uses `created_at` timestamp as a tie-breaker.

5. **Responsive Patient UI**:
   - Modern Bootstrap 5 interface for patient registration, token viewing, and live department queue tracking.

---

## Beginners Windows Setup Guide

Follow these simple steps in **PowerShell** or **Command Prompt** on Windows:

### Step 1: Open Terminal in Project Folder
Open PowerShell and navigate to your project directory:
```powershell
cd C:\Users\Hp\Documents\smart-hospital-queue
```

### Step 2: (Optional) Create and Activate Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### Step 3: Install Required Dependencies
```powershell
pip install -r requirements.txt
```

### Step 4: Seed Sample Database
Populate SQLite database (`hospital.db`) with sample departments, doctors, and patients:
```powershell
python seed_data.py
```

### Step 5: Run Automated Tests
Verify that all unit and integration tests pass:
```powershell
python -m pytest
```

### Step 6: Start the Flask Web Application
```powershell
python run.py
```
Open your web browser and navigate to:
**`http://127.0.0.1:5000`**

---

## File Structure

```
smart-hospital-queue/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── config.py            # Environment configuration
│   ├── models/              # Database schema (User, Dept, Doctor, Patient, Token)
│   ├── routes/              # Page handlers and REST API
│   ├── services/            # Queue Engine & Secure QR Service
│   ├── static/              # CSS styles & dynamic JS scripts
│   └── templates/           # Jinja2 HTML templates
├── tests/                   # Automated pytest suite
├── seed_data.py             # Sample data generator
├── requirements.txt         # Dependencies list
├── run.py                   # App launcher
└── README.md                # Documentation & Setup guide
```

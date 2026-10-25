# Smart Hospital Queue Management System

A production-ready outpatient department (OPD) hospital queue management system built with Python Flask, SQLAlchemy, Machine Learning wait-time estimation, and ESP8266 IoT edge displays.

---

## 1. System Architecture Overview

```
+---------------------------------------------------------------------------------------------------+
|                                          CLIENT LAYER                                             |
|  [ Patient Portal ]     [ QR Check-In Scanner ]    [ Doctor Dashboard ]    [ Admin Queue Panel ]  |
|  - Registration         - Anti-tamper UUID lookup  - Atomic 'Call Next'    - Multi-dept filters   |
|  - Live Status View     - Non-PII scan             - State transitions     - Priority overrides   |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+---------------------------------------------------------------------------------------------------+
|                                         FLASK APP LAYER                                           |
|                                                                                                   |
|  +───────────────────────────────────────────+   +─────────────────────────────────────────────+  |
|  |           AUTHORITATIVE QUEUE ENGINE      |   |            ML WAITING TIME PREDICTOR        |  |
|  | - Priority: Emergency, High, Medium, Normal|   | - Advisory wait estimates (mins)            |  |
|  | - Fairness Aging: +10 pts per 15 min wait |   | - STRICTLY READ-ONLY: Never alters ordering |  |
|  | - Atomic concurrency guards               |   | - Fallback: Graceful degradation if missing |  |
|  +───────────────────────────────────────────+   +─────────────────────────────────────────────+  |
|                                                  │                                                |
|  +───────────────────────────────────────────+   │                                                |
|  |       AUTHENTICATED DEVICE REST API       |   │                                                |
|  | - Header: X-Device-API-Key                |   │                                                |
|  | - Sequential QueueCallEvent tracking      |   │                                                |
|  | - Strictly ZERO PII exposed               |   │                                                |
|  +───────────────────────────────────────────+   │                                                |
+--------------------------------------------------┼------------------------------------------------+
                                                   │
                                                   ▼
+--------------------------------------------------+------------------------------------------------+
|                                           DATA LAYER                                              |
|  - SQLite (hospital.db) with SQLAlchemy ORM                                                       |
|  - Relational Models: User, Department, Doctor, Patient, QueueToken, QueueCallEvent               |
+---------------------------------------------------------------------------------------------------+
                                                   │
                                                   ▼
+---------------------------------------------------------------------------------------------------+
|                                      IOT HARDWARE LAYER                                           |
|  - Microcontroller: ESP32 DevKit V1 (Primary) / NodeMCU ESP8266 (Legacy)                         |
|  - Display: 0.96" SSD1306 I2C OLED (Live Token, Next Token, Waiting Count, Status)                |
|  - Sound: Active Buzzer Module (Single 250ms chime on new doctor call events)                     |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Completed Project Phases

| Phase | Description | Key Deliverables |
| :--- | :--- | :--- |
| **Phase 1** | Patient Registration & Tokens | Online/walk-in intake, sequential token generation (`GEN-20261025-001`), secure non-PII QR codes. |
| **Phase 2** | Doctor Dashboard & Workflow | Doctor authentication, atomic `Call Next Patient`, `In-Consultation`, `Completed`, `No-Show`, queue recovery. |
| **Phase 3** | Fairness Aging & Admin Panel | Starvation-prevention aging algorithm (+10 pts / 15 mins), role-based admin oversight, triage priority overrides. |
| **Phase 4** | Machine Learning Estimation | Waiting-time regression model (Pipeline + Scaler + OneHotEncoder + Regressor), queue-order invariant, graceful fallbacks. |
| **Phase 5** | ESP8266 IoT Integration | Authenticated edge API, sequential `QueueCallEvent` tracking, ESP8266 firmware, OLED layout, non-blocking active buzzer. |

---

## 3. Quick Start & Setup Guide (Windows)

### Prerequisites
- Python 3.10+ (tested on Python 3.15)
- Git (optional)

### Step 1: Navigate to Workspace
```powershell
cd smart-hospital-queue
```

### Step 2: Install Dependencies
```powershell
pip install -r requirements.txt
```

> [!CAUTION]
> **DATABASE SAFETY PRECAUTION:**
> - **NEVER run `seed_data.py`** in an existing installation. It drops and recreates tables, destroying live hospital and patient records.
> - `hospital.db` is pre-configured and preserved with real departments, doctors, and schema tables.

### Step 3: Run Automated Test Suite
Verify that all unit, integration, ML, and IoT regression tests pass:
```powershell
python -m pytest tests/
```
*(All 159 automated tests must pass before running the application).*

### Step 4: Launch Flask Web Application
```powershell
# For local testing:
python run.py

# For network testing with ESP8266 on local Wi-Fi:
$env:HOST="0.0.0.0"
$env:PORT=5000
python run.py
```
Open your browser to: **`http://localhost:5000`**

---

## 4. Default User Credentials

| Role | Username | Password | Access / Purpose |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin` | `admin123` | System admin, queue inspection, priority overrides (`/admin/dashboard`) |
| **Doctor** | `dr_smith` | `doctor123` | General Medicine doctor dashboard, calling patients (`/doctor/dashboard`) |
| **Patient** | *Unauthenticated* | *N/A* | Public registration, live token status, QR verification (`/register`, `/token/...`) |
| **IoT Device** | *Header Auth* | `dev-esp8266-secret-key-2026` | Read-only hardware display polling (`/api/v1/device/queue/...`) |

---

## 5. REST API Endpoints

### 1. Public Token Status (Privacy-Safe)
`GET /api/v1/token/<token_number>`
- **Auth**: None required.
- **Privacy**: Returns strictly non-PII token details (`department`, `status`, `priority`, `created_at`, `waiting_duration_mins`, `estimated_wait_mins`). Patient names, phone numbers, and appointment notes are omitted.

### 2. Department Queue Status
`GET /api/v1/queue/<department_id>`
- **Auth**: Staff / Internal.
- **Payload**: Ordered token list with priority scores and estimated waiting times.

### 3. IoT Edge Device Queue Endpoint
`GET /api/v1/device/queue/<department_identifier>`
- **Auth**: Header `X-Device-API-Key: <DEVICE_API_KEY>` (or `Authorization: Bearer <key>`).
- **Identifier**: Numeric department ID (e.g. `1`) or department code (`GEN`, `CARD`, `ORTHO`).
- **Payload**:
  ```json
  {
    "status": "online",
    "department_id": 1,
    "department_code": "GEN",
    "department_name": "General Medicine",
    "waiting_count": 3,
    "current_token": "GEN-20261025-001",
    "current_status": "Called",
    "last_called_token": "GEN-20261025-001",
    "next_token": "GEN-20261025-002",
    "call_event_id": 4,
    "server_time": "2026-10-25T15:00:00Z"
  }
  ```

---

## 6. Machine Learning Methodology & Disclaimers

- **Algorithm**: Scikit-Learn Regression Pipeline (`StandardScaler` + `OneHotEncoder` + `RandomForestRegressor`).
- **Feature Set**: Department, clinical priority, registration type, elapsed wait time, queue depth ahead, active doctor count, doctor average consultation speed.
- **Strict Architecture Invariance**: ML predictions are strictly advisory. The Queue Engine determines patient sequence solely by base clinical priority scores and waiting-time aging. Predictions NEVER alter queue priority or order.
- **Graceful Fallback**: If the ML model file is absent or corrupted, the system falls back seamlessly to rule-based heuristics without crashing.
- **Synthetic Data Disclaimer**: Model training utilized simulated OPD arrival distributions. Synthetic metrics do not represent real-world clinical validation.

---

## 7. IoT Hardware Setup (Phase 5)

Complete hardware documentation, wiring diagrams, Arduino IDE instructions, and source code are located in:
- **Comprehensive Guide**: [`PHASE5_IOT_GUIDE.md`](PHASE5_IOT_GUIDE.md)
- **ESP32 Firmware (Primary)**: [`hardware/esp32_queue_display/esp32_queue_display.ino`](hardware/esp32_queue_display/esp32_queue_display.ino)
- **ESP32 Config Template**: [`hardware/esp32_queue_display/config.h.example`](hardware/esp32_queue_display/config.h.example)
- **ESP32 Hardware Specs & Pinout**: [`hardware/esp32_queue_display/README.md`](hardware/esp32_queue_display/README.md)
- **ESP8266 Firmware (Legacy)**: [`hardware/esp8266_queue_display/esp8266_queue_display.ino`](hardware/esp8266_queue_display/esp8266_queue_display.ino)

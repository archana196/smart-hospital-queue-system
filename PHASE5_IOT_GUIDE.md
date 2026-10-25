# Phase 5 IoT Hardware Integration Guide
## ESP32 DevKit V1 (Primary) / ESP8266 (Legacy) + 0.96" I2C OLED + Active Buzzer

This guide provides end-to-end instructions for assembling, wiring, configuring, and verifying the IoT physical queue display edge device for the **Smart Hospital Queue Management System**.

---

## 1. System Architecture & Workflow

```
[ Doctor Dashboard (Web) ]
           │
           │ Doctor clicks "Call Next Patient"
           ▼
[ Flask Backend / DoctorService ]
           │
           ├── 1. Claims patient atomically ('Waiting' → 'Called')
           ├── 2. Emits sequential QueueCallEvent (ID: N)
           └── 3. Commits to hospital.db
           │
           ▼
[ REST API: /api/v1/device/queue/<DEPT_CODE> ] (Protected via X-Device-API-Key)
           ▲
           │ Wi-Fi HTTP Polling (every ~3 seconds)
           │
[ ESP32 DevKit V1 Edge Controller ]
           ├── Parses JSON payload (ArduinoJson v6/v7)
           ├── Checks: is call_event_id > last_seen_event_id?
           │
           ├─► YES: Triggers Active Buzzer (single 250ms chime via non-blocking millis)
           │        Persists last_seen_event_id in EEPROM/NVS (anti-reboot duplicate chime)
           │
           └─► Updates SSD1306 OLED Display (Flicker-free, overflow-protected redraw):
               - Department Name & [LIVE] indicator
               - "NOW SERVING: <Token>" (Dynamic sizing: text size 2 for ≤9 chars, size 1 for >9 chars)
               - "NEXT: <Token>"
               - "WAIT: <Count>  [Called]"
```

---

## 2. Hardware Bill of Materials (BOM)

| Component | Quantity | Specification / Recommendation | Purpose |
| :--- | :---: | :--- | :--- |
| **Microcontroller** | 1 | **ESP32 DevKit V1** (ESP-WROOM-32, 30-pin or 36-pin) | Edge Wi-Fi client and controller |
| **OLED Display** | 1 | 0.96" Monochrome I2C OLED (SSD1306 128x64) | Displays real-time token, next token, and wait counts |
| **Active Buzzer** | 1 | 3.3V / 5V **Active Buzzer Module** (3-pin with transistor) | Emits single audible alert for new calls |
| **Jumper Wires** | 7 | Female-to-Female Dupont Wires | Direct board-to-module interconnection |
| **Power Supply** | 1 | Standard Micro-USB Cable (5V, >= 1A) | Powers ESP32 and attached peripherals |

---

## 3. Circuit Wiring & Pinout Tables

### Primary: ESP32 DevKit V1 Pin Assignment

| Module | Module Pin | ESP32 Pin | GPIO | Recommended Wire Color | Functional Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OLED (SSD1306)** | `VCC` | `3V3` | 3.3V | Red | 3.3V DC Power Supply |
| **OLED (SSD1306)** | `GND` | `GND` | Ground | Black | Common System Ground |
| **OLED (SSD1306)** | `SCL` | `D22` | GPIO 22 | Yellow | Hardware I2C Clock Line (SCL) |
| **OLED (SSD1306)** | `SDA` | `D21` | GPIO 21 | Blue | Hardware I2C Data Line (SDA) |
| **Active Buzzer** | `VCC` / `+` | `3V3` or `VIN` | 3.3V/5V | Red | Power Rail |
| **Active Buzzer** | `GND` / `-` | `GND` | Ground | Black | Common System Ground |
| **Active Buzzer** | `I/O` / `S` | `D25` | GPIO 25 | Green | Digital Output Signal (Active HIGH/LOW configurable) |

### Legacy: NodeMCU ESP8266 Pin Assignment (Reference)

| Module | Module Pin | NodeMCU Pin | GPIO | Recommended Wire Color | Functional Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OLED (SSD1306)** | `VCC` | `3V3` | 3.3V | Red | 3.3V DC Power Supply |
| **OLED (SSD1306)** | `GND` | `GND` | Ground | Black | Common Ground |
| **OLED (SSD1306)** | `SCL` | `D1` | GPIO 5 | Yellow | I2C Clock Line (SCL) |
| **OLED (SSD1306)** | `SDA` | `D2` | GPIO 4 | Blue | I2C Data Line (SDA) |
| **Active Buzzer** | `I/O` / `S` | `D5` | GPIO 14 | Green | Digital Output Signal |

### Electrical Safety Guidelines:
- **Active Buzzer Module Requirement**: Use an **active buzzer module** equipped with an onboard switching transistor (S8050 or equivalent). Connecting a raw passive coil directly to an ESP32 or ESP8266 GPIO pin can draw excessive current (>15mA), which risks damaging the microcontroller or causing brownout resets. If using a bare buzzer, drive it via an external NPN transistor (e.g. 2N2222) with a 1kΩ base resistor and flyback diode.
- **I2C Bus Pullups**: Standard 0.96" SSD1306 breakout boards already include onboard 4.7kΩ pull-up resistors on the SDA and SCL lines. No external resistors are necessary.
- **I2C Address**: The firmware defaults to address `0x3C`. If your OLED uses address `0x3D` (selectable via a solder jumper on the back of some breakout boards), change `OLED_I2C_ADDR` in `config.h`.

---

## 4. Backend Device API Reference

### Endpoint
`GET /api/v1/device/queue/<department_identifier>`

### Authentication
- Header: `X-Device-API-Key: <DEVICE_API_KEY>`  
  *(Alternative: `Authorization: Bearer <DEVICE_API_KEY>`)*
- Requests missing or carrying an invalid key return `401 Unauthorized`.
- Credentials in URL parameters are rejected.

### Path Parameter
- `<department_identifier>`: Department code (e.g. `GEN`, `CARD`, `ORTHO`) or numeric department ID (e.g. `1`). Case-insensitive.

### Success Response (`200 OK`)
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

### Privacy & Security Guarantees:
- **Zero PII**: No patient names, phone numbers, ages, genders, medical notes, or user credentials.
- **Read-Only**: GET requests have no mutating side effects on the database or queue state.
- **Idempotent**: Repeated device polling does NOT advance call events or change token statuses.

---

## 5. Arduino IDE Setup & Flashing Instructions (ESP32 DevKit V1)

### Step 1: Install ESP32 Board Core
1. Open **Arduino IDE** (v2.x recommended).
2. Go to **File → Preferences**.
3. In **Additional boards manager URLs**, add:
   ```text
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Open **Tools → Board → Boards Manager**, search for `esp32` by **Espressif Systems**, and install the latest stable version.

### Step 2: Install Required Libraries
Open **Tools → Manage Libraries...** and install:
1. `Adafruit SSD1306` (by Adafruit)
2. `Adafruit GFX Library` (by Adafruit)
3. `ArduinoJson` (by Benoit Blanchon — version 6.x or 7.x supported)

### Step 3: Configure Device Firmware
1. Navigate to:
   ```powershell
   smart-hospital-queue\hardware\esp32_queue_display\
   ```
2. Copy `config.h.example` to `config.h`:
   ```powershell
   Copy-Item config.h.example config.h
   ```
3. Open `config.h` and configure:
   ```cpp
   #define WIFI_SSID           "Your_WiFi_Network"
   #define WIFI_PASSWORD       "Your_WiFi_Password"
   #define SERVER_HOST         "192.168.1.100"  // Local IPv4 address of machine running Flask
   #define SERVER_PORT         5000
   #define DEPT_CODE           "GEN"            // Department code to monitor
   #define DEVICE_API_KEY      "dev-esp8266-secret-key-2026"
   #define OLED_SDA_PIN        21               // GPIO 21
   #define OLED_SCL_PIN        22               // GPIO 22
   #define BUZZER_PIN          25               // GPIO 25
   #define BUZZER_ACTIVE_HIGH  true
   #define ENABLE_STARTUP_BEEP false            // Disabled by default
   ```

### Step 4: Compile & Flash
1. Connect ESP32 DevKit V1 via Micro-USB.
2. Select **Tools → Board → ESP32 Arduino → DOIT ESP32 DEVKIT V1** (or `ESP32 Dev Module`).
3. Select your serial COM port (**Tools → Port**).
4. Click **Upload** (`Ctrl+U`).

---

## 6. End-to-End Live Demo Procedure

1. **Start the Flask Backend on Local Network**:
   ```powershell
   $env:HOST="0.0.0.0"
   $env:PORT=5000
   python run.py
   ```
2. **Power up ESP32 DevKit V1**:
   - The OLED shows the startup screen, connects to Wi-Fi, syncs with the server's current event ID, and displays the current queue state.
3. **Register Waiting Patients**:
   - Open browser at `http://localhost:5000/register`.
   - Register a patient for General Medicine.
   - Observe the OLED footer update: `WAIT: 1`.
4. **Log into Doctor Dashboard**:
   - Navigate to `http://localhost:5000/auth/login`.
   - Log in as doctor (`dr_smith` / `doctor123` or your configured doctor credentials).
5. **Click "Call Next Patient"**:
   - The doctor dashboard updates to show the patient as `Called`.
   - Within ~3 seconds (next poll cycle), the ESP32 detects the incremented `call_event_id`.
   - The **Active Buzzer emits a single 250ms chime**.
   - The **OLED refreshes** showing:
     - `NOW SERVING: GEN-20261025-001` (dynamically centered)
     - `WAIT: 0  [Called]`
6. **Reboot the ESP32**:
   - Press the EN/RST button on the ESP32.
   - The device re-reads `lastCallEventId` from EEPROM upon boot and synchronizes with the server.
   - Because the event was already handled, it displays the token **without buzzing again**.

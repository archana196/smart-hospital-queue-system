# ESP32 DevKit V1 + OLED + Buzzer Hardware Integration Guide

This guide details how to assemble, wire, configure, and operate the **ESP32 DevKit V1** edge display and alert unit for the Smart Hospital Queue Management System.

---

## 1. Hardware Bill of Materials (BOM)

| Component | Specification | Notes |
| :--- | :--- | :--- |
| **Microcontroller** | **ESP32 DevKit V1** (ESP-WROOM-32, 30-pin or 36-pin) | 240MHz dual-core, 520KB SRAM, 4MB Flash, Wi-Fi 802.11 b/g/n |
| **Display** | 0.96-inch Monochrome I2C OLED (SSD1306 128x64) | 3.3V logic, I2C address `0x3C` |
| **Buzzer** | 3.3V / 5V **Active Buzzer Module** | Must be an **Active** module with an onboard transistor driver |
| **Jumper Wires** | Female-to-Female Dupont Wires (x7) | For direct module interconnection |
| **Power Supply** | Micro-USB Cable (5V, >= 1A) | Connected to PC USB port or 5V USB wall adapter |

---

## 2. Wiring Schematic & Pinout Table

### ESP32 DevKit V1 Pin Assignment

| Peripheral | Module Pin | ESP32 Pin | GPIO | Wire Color (Rec.) | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OLED (SSD1306)** | `VCC` | `3V3` | 3.3V | Red | 3.3V DC Power Rail |
| **OLED (SSD1306)** | `GND` | `GND` | Ground | Black | Common System Ground |
| **OLED (SSD1306)** | `SCL` | `D22` | GPIO 22 | Yellow | Hardware I2C Clock (SCL) |
| **OLED (SSD1306)** | `SDA` | `D21` | GPIO 21 | Blue | Hardware I2C Data (SDA) |
| **Active Buzzer** | `VCC` / `+` | `3V3` or `VIN` | 3.3V / 5V | Red | Power Rail |
| **Active Buzzer** | `GND` / `-` | `GND` | Ground | Black | Common System Ground |
| **Active Buzzer** | `I/O` / `S` | `D25` | GPIO 25 | Green | Digital Buzzer Trigger |

> [!WARNING]
> **Active Buzzer vs Bare Electromagnetic Transducer:**
> - Ensure you are using an **Active Buzzer Module** (typically a 3-pin board with `VCC`, `GND`, `I/O` and an integrated switching transistor such as S8050).
> - **DO NOT connect a bare magnetic buzzer coil directly between an ESP32 GPIO pin and GND.** ESP32 GPIO pins are rated for a maximum of 12–20mA. Drawing raw inductive current directly from GPIO 25 will cause reset loops, GPIO latch-up, or permanent chip damage. If you only have a bare buzzer, drive it via an external NPN transistor (e.g. 2N2222) with a 1kΩ base resistor and 1N4148 flyback diode.

---

## 3. Arduino IDE Setup & Library Installation

### Step 1: Install ESP32 Board Package
1. Open **Arduino IDE** (v2.x recommended).
2. Go to **File → Preferences**.
3. In **Additional boards manager URLs**, add:
   ```text
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Open **Tools → Board → Boards Manager**, search for `esp32` by **Espressif Systems**, and install the latest stable version (2.0.x or 3.0.x).

### Step 2: Install Required Libraries
Open **Tools → Manage Libraries...** and install:
1. `Adafruit SSD1306` (by Adafruit)
2. `Adafruit GFX Library` (by Adafruit)
3. `ArduinoJson` (by Benoit Blanchon — version 6.x or 7.x supported)

---

## 4. Firmware Configuration

1. In the `hardware/esp32_queue_display/` directory, copy `config.h.example` to `config.h`:
   ```bash
   cp config.h.example config.h
   ```
2. Open `config.h` in your editor and configure:
   - `WIFI_SSID`: Your local 2.4GHz Wi-Fi network name.
   - `WIFI_PASSWORD`: Your Wi-Fi password.
   - `SERVER_HOST`: The local IPv4 address of the computer running Flask (e.g. `192.168.1.100` — check via `ipconfig` on Windows). **Do not use `127.0.0.1` or `localhost`**.
   - `SERVER_PORT`: Flask server port (default: `5000`).
   - `DEPT_CODE`: Target clinic department code (e.g. `GEN`, `CARD`, `ORTHO`).
   - `DEVICE_API_KEY`: Must match `Config.DEVICE_API_KEY` on the Flask server (`dev-esp8266-secret-key-2026`).
   - `OLED_SDA_PIN`: `21`
   - `OLED_SCL_PIN`: `22`
   - `OLED_I2C_ADDR`: `0x3C`
   - `BUZZER_PIN`: `25`
   - `BUZZER_ACTIVE_HIGH`: `true` (or `false` for active-LOW modules)
   - `ENABLE_STARTUP_BEEP`: `false` (disabled by default)

---

## 5. Compiling & Flashing

1. Connect the ESP32 DevKit V1 to your computer using a data-capable Micro-USB cable.
2. In Arduino IDE:
   - **Board**: Select `DOIT ESP32 DEVKIT V1` (or `ESP32 Dev Module`).
   - **Upload Speed**: `115200` or `921600`.
   - **Flash Frequency**: `80MHz`.
   - **Port**: Select the COM port corresponding to your ESP32 (e.g. `COM3`, `COM5`).
3. Click **Upload** (`Ctrl + U`).
   *(Note: If the upload hangs at `Connecting........_____`, press and hold the **BOOT** button on the ESP32 until the flashing progress bar begins).*

---

## 6. OLED Display Layout & Text Overflow Protection

The firmware dynamically formats content to prevent text clipping on the 128×64 OLED:

```text
┌──────────────────────────────┐
│ General Med           [LIVE] │  <- Y=0..10: Dept name + live indicator
│ ──────────────────────────── │
│ NOW SERVING:                 │  <- Y=13..21: Section header
│       GEN-20261025-001       │  <- Y=23..35: Dynamically centered token
│ NEXT: GEN-20261025-002       │  <- Y=38..47: Next eligible patient
│ ──────────────────────────── │
│ WAIT: 3             [Called] │  <- Y=50..63: Waiting count & room status
└──────────────────────────────┘
```

- **Dynamic Token Sizing**:
  - Tokens ≤ 9 characters render at **Text Size 2** (prominent font).
  - Tokens > 9 characters (e.g. standard 16-character hospital tokens like `GEN-20261025-001`) render centered at **Text Size 1** so the full string fits without truncation or vertical wrapping.
- **Initialization Guard**: If the OLED is disconnected or fails I2C communication, drawing functions are bypassed safely without blocking or bus corruption.

---

## 7. Event Synchronization & Buzzer Behavior

1. **Reboot Protection**:
   - The ESP32 saves the latest processed `call_event_id` in non-volatile storage (EEPROM/NVS).
   - Upon reboot, it synchronizes with the server's current event ID. It does **not** re-beep or falsely claim to replay historical calls.
2. **New Call Detection**:
   - When a doctor clicks **Call Next Patient** on the web dashboard, the server generates a new sequential event (`call_event_id`).
   - On the next poll (~3s), the ESP32 detects `call_event_id > lastCallEventId`.
   - The buzzer emits a crisp **single 250ms chime** via non-blocking `millis()`, and the new ID is committed to EEPROM.
3. **Repeated Polling Safety**:
   - GET requests to `/api/v1/device/queue/<DEPT>` are read-only and idempotent. Polling never increments event IDs or changes queue state.

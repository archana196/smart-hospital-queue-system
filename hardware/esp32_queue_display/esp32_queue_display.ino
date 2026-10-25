/**
 * ─────────────────────────────────────────────────────────────────────────────
 * SMART HOSPITAL QUEUE SYSTEM — ESP32 DEVKIT V1 FIRMWARE
 * Production Firmware for ESP32 + 0.96" SSD1306 I2C OLED + Active Buzzer
 * 
 * Hardware:
 *   - Controller: ESP32 DevKit V1 (ESP-WROOM-32, 30/36-pin)
 *   - Display:    0.96" I2C Monochrome OLED Display (SSD1306 128x64)
 *   - Buzzer:     3.3V / 5V Active Buzzer Module (with transistor driver)
 * 
 * Pinout (ESP32 DevKit V1):
 *   - OLED SDA:   GPIO 21 (Hardware I2C SDA)
 *   - OLED SCL:   GPIO 22 (Hardware I2C SCL)
 *   - OLED VCC:   3.3V (or 5V/VIN if supported by module breakout)
 *   - OLED GND:   GND
 *   - Buzzer I/O: GPIO 25 (Configurable digital output)
 *   - Buzzer VCC: 3.3V or 5V (VIN)
 *   - Buzzer GND: GND
 * 
 * Required Arduino Libraries:
 *   - WiFi (built-in with ESP32 board core)
 *   - HTTPClient (built-in with ESP32 board core)
 *   - Wire (built-in with ESP32 board core)
 *   - EEPROM (built-in with ESP32 board core)
 *   - Adafruit GFX Library (by Adafruit)
 *   - Adafruit SSD1306 (by Adafruit)
 *   - ArduinoJson (v6 or v7 by Benoit Blanchon)
 * ─────────────────────────────────────────────────────────────────────────────
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <EEPROM.h>

// Load configuration header.
// If config.h is not found, fallback to config.h.example
#if __has_include("config.h")
  #include "config.h"
#else
  #include "config.h.example"
#endif

// ── Display Object & Initialization Guard ────────────────────────────────────
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
bool oledInitialized = false;

// ── EEPROM Constants for Call Event Persistence ──────────────────────────────
#define EEPROM_SIZE          16
#define EEPROM_MAGIC_BYTE0   0x53  // 'S'
#define EEPROM_MAGIC_BYTE1   0x48  // 'H'
#define EEPROM_ADDR_MAGIC    0
#define EEPROM_ADDR_EVENT    2

// ── Global Runtime State ──────────────────────────────────────────────────────
uint32_t lastCallEventId   = 0;
bool     isFirstPoll       = true;

// Non-blocking buzzer state
bool          buzzerIsActive   = false;
unsigned long buzzerStartTime  = 0;

// Timing
unsigned long lastPollTime     = 0;
unsigned long lastReconnectAttempt = 0;

// Cached state for flicker-free display updates
String   cachedCurrentToken = "";
String   cachedNextToken    = "";
int      cachedWaitingCount = -1;
String   cachedDeptName     = "";
String   cachedStatusMsg    = "";
bool     cachedOnlineState  = false;

// ── Function Declarations ─────────────────────────────────────────────────────
void initEEPROM();
void loadLastCallEventId();
void saveLastCallEventId(uint32_t eventId);
void buzzerOn();
void buzzerOff();
void buzzerTrigger();
void updateBuzzer();
void displayConnecting(const String& ssid);
void displayError(const String& line1, const String& line2);
void displayQueueState(const String& deptName, const String& currentToken, const String& nextToken, int waitingCount, const String& status);
void pollQueueServer();

// ─────────────────────────────────────────────────────────────────────────────
// SETUP
// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println(F("=================================================="));
  Serial.println(F("  Smart Hospital Queue — ESP32 Edge Display"));
  Serial.println(F("=================================================="));

  // Initialize Buzzer
  pinMode(BUZZER_PIN, OUTPUT);
  buzzerOff();

  // Initialize EEPROM / NVS
  initEEPROM();

  // Initialize I2C and OLED Display
  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  oledInitialized = display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR);
  if (!oledInitialized) {
    Serial.println(F("[ERROR] SSD1306 OLED initialization failed! Check wiring & I2C address."));
  } else {
    Serial.println(F("[OK] SSD1306 OLED initialized successfully."));
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(18, 14);
    display.println(F("SMART HOSPITAL"));
    display.setCursor(18, 27);
    display.println(F("QUEUE SYSTEM"));
    display.setCursor(18, 44);
    display.println(F("ESP32 Starting..."));
    display.display();
    delay(1000);
  }

  // Connect to Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print(F("Connecting to Wi-Fi SSID: "));
  Serial.println(WIFI_SSID);
  displayConnecting(WIFI_SSID);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(500);
    Serial.print(F("."));
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("[OK] Connected to Wi-Fi. IP: "));
    Serial.println(WiFi.localIP());

    // Optional startup beep (disabled by default in config)
    #if defined(ENABLE_STARTUP_BEEP) && (ENABLE_STARTUP_BEEP == true)
      buzzerTrigger();
    #endif
  } else {
    Serial.println(F("[WARN] Wi-Fi connection timed out. Will retry in loop."));
    displayError(F("Wi-Fi Error"), F("Retrying..."));
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN LOOP
// ─────────────────────────────────────────────────────────────────────────────
void loop() {
  // Service non-blocking buzzer state
  updateBuzzer();

  // Monitor Wi-Fi connection
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastReconnectAttempt >= 3000) {
      lastReconnectAttempt = millis();
      Serial.println(F("[WARN] Wi-Fi disconnected. Reconnecting..."));
      displayConnecting(WIFI_SSID);
      WiFi.reconnect();
    }
    return;
  }

  // Periodic HTTP polling of Flask backend
  if (millis() - lastPollTime >= POLL_INTERVAL_MS) {
    lastPollTime = millis();
    pollQueueServer();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// HTTP POLLING & EVENT PROCESSING
// ─────────────────────────────────────────────────────────────────────────────
void pollQueueServer() {
  HTTPClient http;

  // Construct REST endpoint URL
  String endpoint = String("http://") + SERVER_HOST + ":" + SERVER_PORT + 
                    "/api/v1/device/queue/" + DEPT_CODE;

  http.setTimeout(HTTP_TIMEOUT_MS);
  
  // ESP32 HTTPClient begin
  if (!http.begin(endpoint)) {
    Serial.println(F("[HTTP] Unable to connect to host"));
    displayError(F("Host Error"), F("Cannot connect"));
    return;
  }

  // Set Device Authentication Headers
  http.addHeader(F("X-Device-API-Key"), DEVICE_API_KEY);
  http.addHeader(F("Accept"), F("application/json"));

  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    String payload = http.getString();

    // Parse JSON safely (compatible with both ArduinoJson v6 and v7)
    #if ARDUINOJSON_VERSION_MAJOR >= 7
      JsonDocument doc;
      DeserializationError err = deserializeJson(doc, payload);
    #else
      StaticJsonDocument<768> doc;
      DeserializationError err = deserializeJson(doc, payload);
    #endif

    if (err) {
      Serial.print(F("[JSON] Parse failed: "));
      Serial.println(err.c_str());
      displayError(F("JSON Error"), F("Parse Failed"));
      http.end();
      return;
    }

    // Extract fields matching Flask backend schema
    const char* deptName   = doc["department_name"] | DEPT_CODE;
    const char* currentTok = doc["current_token"] | "";
    const char* lastCalled = doc["last_called_token"] | "";
    const char* nextTok    = doc["next_token"] | "";
    int waitingCount       = doc["waiting_count"] | 0;
    uint32_t callEventId   = doc["call_event_id"] | 0;
    const char* curStatus  = doc["current_status"] | "Idle";

    // Determine token to display in "NOW SERVING" slot:
    // If active token exists, show it; otherwise show last called or "---"
    String displayToken = String(currentTok);
    if (displayToken.length() == 0 && String(lastCalled).length() > 0) {
      displayToken = String(lastCalled);
    }
    if (displayToken.length() == 0) {
      displayToken = F("---");
    }

    String displayNext = String(nextTok);
    if (displayNext.length() == 0) {
      displayNext = F("---");
    }

    // ── Call Event & Buzzer Evaluation ──────────────────────────────────────
    if (callEventId > 0) {
      if (isFirstPoll) {
        // Startup synchronization:
        // Sync with the server's current event ID without replaying historical calls.
        Serial.printf("[SYNC] Device synced to current server call event: #%u\n", callEventId);
        lastCallEventId = callEventId;
        saveLastCallEventId(callEventId);
        isFirstPoll = false;
      } else if (callEventId > lastCallEventId) {
        // A genuinely new call event was triggered by the doctor!
        Serial.printf("[EVENT] *** NEW CALL EVENT #%u (Token: %s) ***\n", callEventId, displayToken.c_str());
        lastCallEventId = callEventId;
        saveLastCallEventId(callEventId);
        buzzerTrigger(); // Single non-blocking 250ms chime
      }
    } else {
      isFirstPoll = false;
    }

    // Update OLED Display (only redraws if state changed)
    displayQueueState(deptName, displayToken, displayNext, waitingCount, curStatus);

  } else if (httpCode == 401) {
    Serial.println(F("[HTTP] 401 Unauthorized - Invalid DEVICE_API_KEY"));
    displayError(F("401 Unauthorized"), F("Invalid API Key"));
  } else if (httpCode == 404) {
    Serial.println(F("[HTTP] 404 Department Not Found"));
    displayError(F("404 Not Found"), F("Unknown Dept"));
  } else {
    Serial.printf("[HTTP] Request failed, code: %d\n", httpCode);
    displayError(F("Server Error"), String("HTTP Code: ") + httpCode);
  }

  http.end();
}

// ─────────────────────────────────────────────────────────────────────────────
// FLICKER-FREE OLED RENDERING (WITH OVERFLOW & INITIALIZATION PROTECTION)
// ─────────────────────────────────────────────────────────────────────────────
void displayQueueState(const String& deptName, const String& currentToken, const String& nextToken, int waitingCount, const String& status) {
  // Guard against uninitialized display
  if (!oledInitialized) return;

  // Check if content has changed to prevent unnecessary redraws & flickering
  if (cachedOnlineState &&
      cachedCurrentToken == currentToken &&
      cachedNextToken    == nextToken &&
      cachedWaitingCount == waitingCount &&
      cachedDeptName     == deptName &&
      cachedStatusMsg    == status) {
    return; // No change, skip redraw
  }

  // Update cached state
  cachedCurrentToken = currentToken;
  cachedNextToken    = nextToken;
  cachedWaitingCount = waitingCount;
  cachedDeptName     = deptName;
  cachedStatusMsg    = status;
  cachedOnlineState  = true;

  display.clearDisplay();

  // 1. Department Header Bar (Y: 0 to 10)
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  
  // Truncate dept name if longer than 14 chars to preserve header spacing
  String headerText = deptName;
  if (headerText.length() > 14) {
    headerText = headerText.substring(0, 14);
  }
  display.print(headerText);

  // Status indicator on top right
  display.setCursor(92, 0);
  display.print(F("[LIVE]"));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  // 2. Current Called Patient Section (Y: 13 to 35)
  display.setCursor(0, 13);
  display.setTextSize(1);
  display.print(F("NOW SERVING:"));

  // Dynamic font sizing to prevent overflow and clipping for long token strings:
  // SSD1306 width = 128px. Font size 2 = 12px/char (fits max 10 chars).
  // Font size 1 = 6px/char (fits up to 21 chars, accommodating "GEN-20261025-001" = 16 chars).
  int tokenLen = currentToken.length();
  if (tokenLen <= 9) {
    display.setTextSize(2);
    int xPos = max(0, (128 - (tokenLen * 12)) / 2);
    display.setCursor(xPos, 23);
    display.print(currentToken);
  } else {
    display.setTextSize(1);
    int xPos = max(0, (128 - (tokenLen * 6)) / 2);
    display.setCursor(xPos, 25);
    display.print(currentToken);
  }

  // 3. Next Eligible Patient Section (Y: 38 to 47)
  display.setTextSize(1);
  display.setCursor(0, 38);
  display.print(F("NEXT: "));
  String displayNext = nextToken;
  if (displayNext.length() > 15) {
    displayNext = displayNext.substring(0, 15);
  }
  display.print(displayNext);

  // 4. Footer Bar: Waiting Count & Doctor Status (Y: 50 to 63)
  display.drawLine(0, 50, 127, 50, SSD1306_WHITE);
  display.setCursor(0, 54);
  display.setTextSize(1);
  display.printf("WAIT: %d", waitingCount);

  display.setCursor(70, 54);
  String statusText = status;
  if (statusText.length() > 8) {
    statusText = statusText.substring(0, 8);
  }
  display.printf("[%s]", statusText.c_str());

  display.display();
}

void displayConnecting(const String& ssid) {
  if (!oledInitialized) return;

  cachedOnlineState = false;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 10);
  display.println(F("Connecting Wi-Fi..."));
  display.setCursor(0, 26);
  display.println(ssid);
  display.setCursor(0, 46);
  display.println(F("Please wait..."));
  display.display();
}

void displayError(const String& line1, const String& line2) {
  if (!oledInitialized) return;

  cachedOnlineState = false;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 5);
  display.println(F("! CONNECTION ALERT !"));
  display.drawLine(0, 16, 127, 16, SSD1306_WHITE);
  
  display.setCursor(0, 24);
  display.setTextSize(1);
  display.println(line1);

  display.setCursor(0, 40);
  display.println(line2);

  display.setCursor(0, 55);
  display.println(F("Retrying in 3s..."));
  display.display();
}

// ─────────────────────────────────────────────────────────────────────────────
// NON-BLOCKING BUZZER CONTROL
// ─────────────────────────────────────────────────────────────────────────────
void buzzerOn() {
  digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_HIGH ? HIGH : LOW);
}

void buzzerOff() {
  digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_HIGH ? LOW : HIGH);
}

void buzzerTrigger() {
  buzzerOn();
  buzzerIsActive  = true;
  buzzerStartTime = millis();
}

void updateBuzzer() {
  if (buzzerIsActive && (millis() - buzzerStartTime >= BEEP_DURATION_MS)) {
    buzzerOff();
    buzzerIsActive = false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// EEPROM EVENT PERSISTENCE (NVS)
// ─────────────────────────────────────────────────────────────────────────────
void initEEPROM() {
  EEPROM.begin(EEPROM_SIZE);
  uint8_t m0 = EEPROM.read(EEPROM_ADDR_MAGIC);
  uint8_t m1 = EEPROM.read(EEPROM_ADDR_MAGIC + 1);

  if (m0 == EEPROM_MAGIC_BYTE0 && m1 == EEPROM_MAGIC_BYTE1) {
    loadLastCallEventId();
    Serial.printf("[EEPROM] Restored last call event ID: %u\n", lastCallEventId);
  } else {
    Serial.println(F("[EEPROM] Formatting fresh EEPROM storage..."));
    EEPROM.write(EEPROM_ADDR_MAGIC, EEPROM_MAGIC_BYTE0);
    EEPROM.write(EEPROM_ADDR_MAGIC + 1, EEPROM_MAGIC_BYTE1);
    lastCallEventId = 0;
    saveLastCallEventId(0);
  }
}

void loadLastCallEventId() {
  uint32_t val = 0;
  for (int i = 0; i < 4; i++) {
    val |= ((uint32_t)EEPROM.read(EEPROM_ADDR_EVENT + i)) << (i * 8);
  }
  lastCallEventId = val;
}

void saveLastCallEventId(uint32_t eventId) {
  for (int i = 0; i < 4; i++) {
    EEPROM.write(EEPROM_ADDR_EVENT + i, (eventId >> (i * 8)) & 0xFF);
  }
  EEPROM.commit();
}

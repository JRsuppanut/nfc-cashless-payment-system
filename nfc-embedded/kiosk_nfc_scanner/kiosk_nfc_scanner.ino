#include <WiFi.h>
#include <HTTPClient.h>
#include <Adafruit_PN532.h>
#include <ArduinoJson.h>

// Network Configuration
const char* WIFI_SSID = "JRnakrab";
const char* WIFI_PASSWORD = "password";

// API Configuration
const char* SERVER_URL = "http://10.137.155.226:8000/api/kiosk/scan";

// UART Configuration for PN532
#define PN532_RX_PIN 16
#define PN532_TX_PIN 17
#define PN532_RESET 3

// Initialize HardwareSerial 1 for ESP32
HardwareSerial PN532Serial(1);

// Initialize Adafruit_PN532 using HardwareSerial
Adafruit_PN532 nfc(PN532_RESET, &PN532Serial);

/**
 * Initializes the WiFi connection.
 */
void setupWiFi() {
    Serial.print("Connecting to WiFi: ");
    Serial.println(WIFI_SSID);
    
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    
    Serial.println("\nWiFi Connected.");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
}

/**
 * Initializes the PN532 NFC module via UART.
 */
void setupNFC() {
    PN532Serial.begin(115200, SERIAL_8N1, PN532_RX_PIN, PN532_TX_PIN);
    
    nfc.begin();
    
    uint32_t versiondata = nfc.getFirmwareVersion();
    if (!versiondata) {
        Serial.println("Error: PN53x board not found. Check wiring.");
        while (1) { delay(10); }
    }
    
    Serial.print("Found chip PN5");
    Serial.println((versiondata >> 24) & 0xFF, HEX);
    
    nfc.SAMConfig();
    Serial.println("Waiting for an ISO14443A Card...");
}

/**
 * Converts a byte array UID to a Hexadecimal String.
 */
String getUIDString(uint8_t* uid, uint8_t uidLength) {
    String uidString = "";
    for (uint8_t i = 0; i < uidLength; i++) {
        if (uid[i] < 0x10) {
            uidString += "0";
        }
        uidString += String(uid[i], HEX);
    }
    uidString.toUpperCase();
    return uidString;
}

/**
 * Sends the scanned card UID to the central server via HTTP POST.
 */
void sendUIDToServer(String cardUID) {
    if (WiFi.status() == WL_CONNECTED) {
        HTTPClient http;
        http.begin(SERVER_URL);
        http.addHeader("Content-Type", "application/json");

        StaticJsonDocument<200> doc;
        doc["card_uid"] = cardUID;
        String requestBody;
        serializeJson(doc, requestBody);

        Serial.println("Sending HTTP POST Request...");
        int httpResponseCode = http.POST(requestBody);

        if (httpResponseCode > 0) {
            Serial.print("HTTP Response Code: ");
            Serial.println(httpResponseCode);
            String response = http.getString();
            Serial.println("Server Response: " + response);
        } else {
            Serial.print("Error Code: ");
            Serial.println(httpResponseCode);
        }
        
        http.end();
    } else {
        Serial.println("Error: WiFi Disconnected.");
    }
}

void setup() {
    Serial.begin(115200);
    while (!Serial) delay(10);
    
    setupWiFi();
    setupNFC();
}

void loop() {
    uint8_t success;
    uint8_t uid[] = { 0, 0, 0, 0, 0, 0, 0 };
    uint8_t uidLength;

    success = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength);

    if (success) {
        Serial.println("Card Detected.");
        String cardUID = getUIDString(uid, uidLength);
        Serial.print("UID: ");
        Serial.println(cardUID);

        sendUIDToServer(cardUID);

        // Prevent multiple scans for a single tap
        delay(3000); 
        Serial.println("Waiting for an ISO14443A Card...");
    }
}
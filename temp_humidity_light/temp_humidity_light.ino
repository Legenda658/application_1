#include <LiquidCrystal.h>
#include <DHT.h>
#include <Wire.h>
#include <BH1750.h>
#define PIN_RS 6
#define PIN_EN 7
#define PIN_DB4 8
#define PIN_DB5 9
#define PIN_DB6 10
#define PIN_DB7 11
#define SOIL_MOISTURE_PIN A0
#define DHT_PIN 2
#define BUTTON_PIN 3
#define LED_PIN 13       
#define CURTAINS_PIN 12  
#define DHT_TYPE DHT22
#define DISPLAY_INTERVAL 5000
enum ProgramState {
  NORMAL_OPERATION
};
enum DisplayMode {
  SOIL_MOISTURE,
  AIR_DATA,
  LIGHT_DATA,
  DEVICES_STATE
};
LiquidCrystal lcd(PIN_RS, PIN_EN, PIN_DB4, PIN_DB5, PIN_DB6, PIN_DB7);
DHT dht(DHT_PIN, DHT_TYPE);
BH1750 lightMeter;
ProgramState currentState = NORMAL_OPERATION;
DisplayMode currentDisplayMode = SOIL_MOISTURE;
int drySoilValue = 1000;  
int wetSoilValue = 200;   
unsigned long lastDisplayChange = 0;
bool lastButtonState = HIGH;
bool buttonState = HIGH;
unsigned long lastDebounceTime = 0;
unsigned long debounceDelay = 50;
bool bh1750_detected = false; 
bool ledState = false;
bool curtainsState = false;
void setup() {
  Serial.begin(9600);
  Wire.begin();
  lcd.begin(16, 2);
  dht.begin();
  pinMode(LED_PIN, OUTPUT);
  pinMode(CURTAINS_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);     
  digitalWrite(CURTAINS_PIN, LOW); 
  Serial.println("Initializing BH1750 sensor...");
  for (int i = 0; i < 3; i++) { 
    if (lightMeter.begin(BH1750::ONE_TIME_HIGH_RES_MODE)) {
      bh1750_detected = true;
      Serial.println("BH1750 sensor initialized successfully!");
      break;
    }
    delay(500);
    Serial.println("Failed to initialize BH1750 sensor, retrying...");
  }
  if (!bh1750_detected) {
    Serial.println("Could not find a valid BH1750 sensor, check wiring!");
  }
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  displaySoilMoistureData();
  Serial.print("Dry soil value: ");
  Serial.println(drySoilValue);
  Serial.print("Wet soil value: ");
  Serial.println(wetSoilValue);
}
void loop() {
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastButtonState) {
    lastDebounceTime = millis();
  }
  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != buttonState) {
      buttonState = reading;
      if (buttonState == LOW) {
        handleButtonPress();
      }
    }
  }
  lastButtonState = reading;
  if (millis() - lastDisplayChange >= DISPLAY_INTERVAL) {
    lastDisplayChange = millis();
    switchToNextDisplay();
  }
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    processCommand(command);
  }
}
void processCommand(String command) {
  if (command.startsWith("LED:")) {
    int state = command.substring(4).toInt();
    ledState = (state == 1);
    digitalWrite(LED_PIN, ledState ? HIGH : LOW);
    Serial.print("LED state changed to: ");
    Serial.println(ledState ? "ON" : "OFF");
    if (currentDisplayMode == DEVICES_STATE) {
      displayDevicesState();
    }
  }
  else if (command.startsWith("CURTAINS:")) {
    int state = command.substring(9).toInt();
    curtainsState = (state == 1);
    digitalWrite(CURTAINS_PIN, curtainsState ? HIGH : LOW);
    Serial.print("Curtains state changed to: ");
    Serial.println(curtainsState ? "CLOSED" : "OPEN");
    if (currentDisplayMode == DEVICES_STATE) {
      displayDevicesState();
    }
  }
}
void switchToNextDisplay() {
  switch (currentDisplayMode) {
    case SOIL_MOISTURE:
      currentDisplayMode = AIR_DATA;
      displayDHTData();
      break;
    case AIR_DATA:
      currentDisplayMode = LIGHT_DATA;
      displayLightData();
      break;
    case LIGHT_DATA:
      currentDisplayMode = DEVICES_STATE;
      displayDevicesState();
      break;
    case DEVICES_STATE:
      currentDisplayMode = SOIL_MOISTURE;
      displaySoilMoistureData();
      break;
  }
}
void handleButtonPress() {
  lastDisplayChange = millis(); 
  switchToNextDisplay();
}
void displaySoilMoistureData() {
  int soilMoistureRaw = analogRead(SOIL_MOISTURE_PIN);
  int soilMoisturePercent = map(soilMoistureRaw, drySoilValue, wetSoilValue, 0, 100);
  soilMoisturePercent = constrain(soilMoisturePercent, 0, 100);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Soil moisture:");
  lcd.setCursor(0, 1);
  lcd.print(soilMoisturePercent);
  lcd.print("%");
  Serial.print("Soil moisture: ");
  Serial.print(soilMoisturePercent);
  Serial.println("%");
}
void displayDHTData() {
  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature();
  if (isnan(humidity) || isnan(temperature)) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("DHT read failed");
    Serial.println("Failed to read from DHT sensor!");
    return;
  }
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Humidity: ");
  lcd.print(humidity, 1);
  lcd.print("%");
  lcd.setCursor(0, 1);
  lcd.print("Temp: ");
  lcd.print(temperature, 1);
  lcd.print("\xDF""C"); 
  Serial.print("Humidity: ");
  Serial.print(humidity);
  Serial.print("% ");
  Serial.print("Temperature: ");
  Serial.print(temperature);
  Serial.println("°C");
}
void displayLightData() {
  float lux = 0;
  if (bh1750_detected) {
    lightMeter.configure(BH1750::ONE_TIME_HIGH_RES_MODE);
    delay(120); 
    lux = lightMeter.readLightLevel();
    if (lux < 0) {
      Serial.println("Invalid BH1750 reading, reinitializing sensor...");
      if (lightMeter.begin(BH1750::ONE_TIME_HIGH_RES_MODE)) {
        delay(120);
        lux = lightMeter.readLightLevel();
      }
    }
    if (lux < 0) lux = 0;
  } else {
    if (lightMeter.begin(BH1750::ONE_TIME_HIGH_RES_MODE)) {
      bh1750_detected = true;
      delay(120);
      lux = lightMeter.readLightLevel();
      if (lux < 0) lux = 0;
    }
  }
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Light level:");
  lcd.setCursor(0, 1);
  if (bh1750_detected) {
    lcd.print(lux, 1);
    lcd.print(" lx");
  } else {
    lcd.print("Sensor error");
  }
  Serial.print("Light level: ");
  Serial.print(lux);
  Serial.println(" lx");
}
void displayDevicesState() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Lamp: ");
  lcd.print(ledState ? "ON" : "OFF");
  lcd.setCursor(0, 1);
  lcd.print("Curtains: ");
  lcd.print(curtainsState ? "CLOSED" : "OPEN");
  Serial.print("Lamp: ");
  Serial.println(ledState ? "ON" : "OFF");
  Serial.print("Curtains: ");
  Serial.println(curtainsState ? "CLOSED" : "OPEN");
} 
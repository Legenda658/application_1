import sys
import os
import time
import threading
import serial
import cv2
import numpy as np
import requests
import json
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QTabWidget, QGridLayout, QFormLayout, QGroupBox, 
                            QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox,
                            QProgressBar, QFrame, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QThread
from PyQt6.QtGui import QPixmap, QImage, QFont, QIcon
def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
                base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
CONFIG_FILE = os.path.join(os.path.expanduser("~"), "fitodomik_config.json")
ICON_FILE = get_resource_path("67fb70c98d5b2.ico")
LOCAL_PATH = os.path.join(os.path.expanduser("~"), "FitoDomik_photos")
API_TOKEN = ''  
CAMERA_INDEX = 0
SERVER_URL = "http://farm429.online/api/upload-image.php"
SENSOR_API_URL = "http://farm429.online/api/save-sensor-data.php"
LED_API_URL = "http://farm429.online/api/get-lamp-state.php"
CURTAINS_API_URL = "http://farm429.online/api/get-curtains-state.php"
THRESHOLDS_API_URL = "http://farm429.online/api/get-thresholds.php"
MAX_ID_API_URL = "http://farm429.online/api/get-max-sensor-id.php"
SERIAL_PORT = 'COM10'
BAUD_RATE = 9600
SAVE_LOCAL = True
OUTPUT_PATH = "plant_analysis.jpg"
FONT_PATH = get_resource_path("arial.ttf")
THRESHOLDS_PRINT_INTERVAL = 60
if SAVE_LOCAL and not os.path.exists(LOCAL_PATH):
    os.makedirs(LOCAL_PATH)
last_temperature = 0.0
last_humidity = 0.0
last_soil_moisture = 0.0
last_light_level = 0.0
last_co2 = 400.0
last_pressure = 1013.25  
last_led_state = None
last_curtains_state = None
last_thresholds = None
last_thresholds_print_time = 0
auth_error_occurred = False
last_used_id = 0  
class SensorMonitoringThread(QThread):
    update_signal = pyqtSignal()
    log_signal = pyqtSignal(str)
    def __init__(self, serial_connection, interval=60):
        super().__init__()
        self.serial_connection = serial_connection
        self.interval = interval
        self.running = False
        self.first_data_collected = False
        self.last_send_time = 0
    def run(self):
        global last_temperature, last_humidity, last_soil_moisture, last_light_level, last_co2, last_pressure
        global last_led_state, last_curtains_state, last_used_id
        last_temperature = -1
        last_humidity = -1
        last_soil_moisture = -1
        last_light_level = -1
        last_co2 = 400
        last_pressure = 1013.25
        self.running = True
        self.log_signal.emit("🧵 Запущен поток мониторинга датчиков")
        while self.running:
            try:
                if self.serial_connection.in_waiting:
                    line = self.serial_connection.readline().decode('utf-8', errors='replace').strip()
                    if not line:
                        continue
                    if line.startswith("LED:") or line.startswith("CURTAINS:"):
                        continue
                    all_data_received = self.update_sensor_values(line)
                    if not self.first_data_collected:
                        if self.check_all_sensors_ready():
                            self.first_data_collected = True
                            self.log_signal.emit("✅ Получены первые данные со всех датчиков")
                    self.update_signal.emit()
                    current_time = time.time()
                    if self.first_data_collected and (current_time - self.last_send_time >= self.interval):
                        if self.save_to_server():
                            self.last_send_time = current_time
                time.sleep(0.1)
            except serial.SerialException as e:
                self.log_signal.emit(f"❌ Ошибка последовательного порта: {str(e)}")
                time.sleep(1)
            except Exception as e:
                self.log_signal.emit(f"❌ Ошибка в потоке мониторинга: {str(e)}")
                time.sleep(1)
    def stop(self):
        self.running = False
        self.wait()
    def update_sensor_values(self, line):
        global last_temperature, last_humidity, last_soil_moisture, last_light_level, last_co2, last_pressure
        try:
            import re
            temp_match = re.search(r'[Tt]emp(?:erature)?\s*:\s*(\d+\.?\d*)', line)
            if temp_match:
                last_temperature = float(temp_match.group(1))
            humidity_match = re.search(r'[Hh]umidity\s*:\s*(\d+\.?\d*)', line)
            if humidity_match:
                last_humidity = float(humidity_match.group(1))
            soil_match = re.search(r'[Ss]oil\s*moisture\s*:\s*(\d+\.?\d*)', line)
            if soil_match:
                last_soil_moisture = float(soil_match.group(1))
            light_match = re.search(r'[Ll]ight\s*level\s*:\s*(\d+\.?\d*)', line)
            if light_match:
                last_light_level = float(light_match.group(1))
            co2_match = re.search(r'[Cc][Oo]2\s*:\s*(\d+\.?\d*)', line)
            if co2_match:
                last_co2 = float(co2_match.group(1))
            pressure_match = re.search(r'[Pp]ressure\s*:\s*(\d+\.?\d*)', line)
            if pressure_match:
                last_pressure = float(pressure_match.group(1))
            self.log_signal.emit(f"📊 Получены данные: {line}")
            return (last_temperature > 0 and 
                    last_humidity > 0 and 
                    last_soil_moisture >= 0 and 
                    last_light_level >= 0)
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при обработке данных датчиков: {str(e)}")
            return False
    def check_all_sensors_ready(self):
        global last_temperature, last_humidity, last_soil_moisture, last_light_level
        return (last_temperature > 0 and 
                last_humidity > 0 and 
                last_soil_moisture >= 0 and 
                last_light_level >= 0)
    def save_to_server(self):
        global last_temperature, last_humidity, last_soil_moisture, last_light_level, last_co2, last_pressure
        global last_led_state, last_curtains_state, last_used_id, API_TOKEN
        try:
            if last_temperature == 0 or last_humidity == 0:
                return False
            max_id = self.get_max_sensor_id()
            next_id = max(max_id + 1, last_used_id + 1)
            self.log_signal.emit(f"Используем ID {next_id} для новой записи (предыдущий макс. ID: {max_id})")
            post_data = {
                'id': next_id,  
                'user_id': 1,
                'temperature': float(last_temperature),
                'humidity': float(last_humidity),
                'soil_moisture': float(last_soil_moisture),
                'light_level': float(last_light_level),
                'co2': int(last_co2),
                'pressure': float(last_pressure),
                'lamp_state': int(last_led_state) if last_led_state is not None else 0,
                'curtains_state': int(last_curtains_state) if last_curtains_state is not None else 0
            }
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Auth-Token': API_TOKEN
            }
            response = requests.post(SENSOR_API_URL, data=post_data, headers=headers)
            if response.status_code == 200:
                try:
                    resp_data = response.json()
                    if resp_data.get('success'):
                        last_used_id = next_id  
                        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        log_message = f"📅 {current_time}\n"
                        log_message += "────────────────────────────────────\n"
                        log_message += f"🆔 ID записи:              {next_id}\n"
                        log_message += f"🌡️ Температура воздуха:    {post_data['temperature']:.1f}°C\n"
                        log_message += f"💧 Влажность воздуха:      {post_data['humidity']:.1f}%\n"
                        log_message += f"🌱 Влажность почвы:        {post_data['soil_moisture']:.1f}%\n"
                        log_message += f"🔆 Уровень освещенности:   {post_data['light_level']:.2f} lx\n"
                        log_message += f"🫧 CO₂ уровень:            {post_data['co2']} ppm\n"
                        log_message += f"🌬️ Атм. давление:          {post_data['pressure']:.2f} hPa\n"
                        log_message += f"💡 Лампа:                  {'включена' if post_data['lamp_state'] == 1 else 'выключена'}\n"
                        log_message += f"🪟 Шторы:                  {'закрыты' if post_data['curtains_state'] == 1 else 'открыты'}\n"
                        log_message += "────────────────────────────────────"
                        self.log_signal.emit(log_message)
                        return True
                    else:
                        self.log_signal.emit(f"❌ Ошибка при отправке данных: {resp_data.get('message', 'Неизвестная ошибка')}")
                        return False
                except json.JSONDecodeError:
                    self.log_signal.emit(f"❌ Ошибка декодирования JSON в ответе")
                    return False
            elif response.status_code == 401:
                self.log_signal.emit("⛔ ОШИБКА АВТОРИЗАЦИИ ⛔")
                return False
            else:
                self.log_signal.emit(f"❌ Сервер вернул код: {response.status_code}")
                return False
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка отправки данных: {str(e)}")
        return False
    def get_max_sensor_id(self):
        try:
            headers = {'X-Auth-Token': API_TOKEN}
            response = requests.get(MAX_ID_API_URL, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and 'max_id' in data:
                    return int(data['max_id'])
                else:
                    self.log_signal.emit(f"❌ Ошибка получения max_id: {data.get('message', 'Неизвестная ошибка')}")
                    return 0
            elif response.status_code == 401:
                self.log_signal.emit("⛔ ОШИБКА АВТОРИЗАЦИИ ⛔")
                return 0
            else:
                self.log_signal.emit(f"❌ Сервер вернул код при запросе max_id: {response.status_code}")
                return 0
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при запросе max_id: {str(e)}")
            return 0
class DevicesControlThread(QThread):
    update_signal = pyqtSignal()
    log_signal = pyqtSignal(str)
    def __init__(self, serial_connection, check_interval=5):
        super().__init__()
        self.serial_connection = serial_connection
        self.check_interval = check_interval
        self.running = False
    def run(self):
        global last_led_state, last_curtains_state, last_thresholds
        self.log_signal.emit("🧵 Запущен поток управления устройствами")
        last_led_state = None
        last_curtains_state = None
        current_lamp_state_from_server = -1
        current_curtains_state_from_server = -1
        last_successful_state_check = 0
        error_count = 0
        max_errors = 3
        self.running = True
        while self.running:
            try:
                current_time = time.time()
                if current_time - last_successful_state_check >= self.check_interval:
                    led_state = self.get_led_state()
                    if led_state is not None:
                        error_count = 0
                        last_successful_state_check = current_time
                        current_lamp_state_from_server = led_state
                        if last_led_state is None or last_led_state != current_lamp_state_from_server:
                            self.log_signal.emit(f"🔔 Обнаружено изменение состояния лампы: {last_led_state if last_led_state is not None else '?'} ➡️ {current_lamp_state_from_server}")
                            if self.send_command("LED", current_lamp_state_from_server):
                                last_led_state = current_lamp_state_from_server
                    curtains_state = self.get_curtains_state()
                    if curtains_state is not None:
                        error_count = 0
                        last_successful_state_check = current_time
                        current_curtains_state_from_server = curtains_state
                        if last_curtains_state is None or last_curtains_state != current_curtains_state_from_server:
                            self.log_signal.emit(f"🔔 Обнаружено изменение состояния штор: {last_curtains_state if last_curtains_state is not None else '?'} ➡️ {current_curtains_state_from_server}")
                            if self.send_command("CURTAINS", current_curtains_state_from_server):
                                last_curtains_state = current_curtains_state_from_server
                global last_thresholds_print_time, THRESHOLDS_PRINT_INTERVAL
                if current_time - last_thresholds_print_time >= THRESHOLDS_PRINT_INTERVAL:
                    current_thresholds = self.get_thresholds()
                    if current_thresholds is not None:
                        last_thresholds = current_thresholds
                self.update_signal.emit()
                time.sleep(1)
            except Exception as e:
                self.log_signal.emit(f"❌ Ошибка в потоке управления устройствами: {str(e)}")
                error_count += 1
                if error_count >= max_errors:
                    self.check_interval = min(30, self.check_interval * 2)  
                    self.log_signal.emit(f"⚠️ Увеличен интервал проверки до {self.check_interval} секунд из-за повторяющихся ошибок")
                    error_count = 0  
                time.sleep(3)
    def stop(self):
        self.running = False
        self.wait()
    def get_led_state(self):
        try:
            headers = {'X-Auth-Token': API_TOKEN}
            response = requests.get(LED_API_URL, headers=headers, timeout=5)
            if response.status_code != 200:
                if response.status_code == 401:
                    self.log_signal.emit("⛔ ОШИБКА АВТОРИЗАЦИИ ⛔")
                else:
                    self.log_signal.emit(f"❌ Ошибка получения состояния лампы: HTTP {response.status_code}")
                return None
            try:
                data = response.json()
                if data.get('success') == True and 'state' in data:
                    state = data.get('state')
                    return 1 if int(state) == 1 else 0
                else:
                    self.log_signal.emit(f"❌ Некорректный формат ответа от API: {data}")
                    return None
            except json.JSONDecodeError as e:
                self.log_signal.emit(f"❌ Ошибка разбора JSON в ответе лампы: {str(e)}")
                return None
        except requests.exceptions.Timeout:
            self.log_signal.emit(f"❌ Таймаут при запросе состояния лампы")
            return None
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при получении состояния лампы: {str(e)}")
            return None
    def get_curtains_state(self):
        try:
            headers = {'X-Auth-Token': API_TOKEN}
            response = requests.get(CURTAINS_API_URL, headers=headers, timeout=5)
            if response.status_code != 200:
                if response.status_code == 401:
                    self.log_signal.emit("⛔ ОШИБКА АВТОРИЗАЦИИ ⛔")
                else:
                    self.log_signal.emit(f"❌ Ошибка получения состояния штор: HTTP {response.status_code}")
                return None
            try:
                data = response.json()
                if data.get('success') == True and 'state' in data:
                    state = data.get('state')
                    return 1 if int(state) == 1 else 0
                else:
                    self.log_signal.emit(f"❌ Некорректный формат ответа от API: {data}")
                    return None
            except json.JSONDecodeError as e:
                self.log_signal.emit(f"❌ Ошибка разбора JSON в ответе штор: {str(e)}")
                return None
        except requests.exceptions.Timeout:
            self.log_signal.emit(f"❌ Таймаут при запросе состояния штор")
            return None
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при получении состояния штор: {str(e)}")
            return None
    def send_command(self, device_type, state):
        try:
            state_value = 1 if state == 1 else 0
            command = f"{device_type}:{state_value}\n"
            if not self.serial_connection.is_open:
                self.log_signal.emit(f"❌ Ошибка: последовательный порт закрыт")
                return False
            self.log_signal.emit(f"📡 Отправляем команду: {command.strip()}")
            self.serial_connection.write(command.encode())
            global last_led_state, last_curtains_state
            if device_type == "LED":
                status_text = "✅ включена" if state_value == 1 else "❌ выключена"
                self.log_signal.emit(f"💡 Лампа: {status_text}")
                last_led_state = state_value
            elif device_type == "CURTAINS":
                status_text = "✅ закрыты" if state_value == 1 else "❌ открыты"
                self.log_signal.emit(f"🪟 Шторы: {status_text}")
                last_curtains_state = state_value
            time.sleep(0.5)
            if self.serial_connection.in_waiting:
                response = self.serial_connection.readline().decode('utf-8', errors='replace').strip()
                if response:
                    self.log_signal.emit(f"🔄 Ответ Arduino: {response}")
            self.update_signal.emit()
            return True
        except serial.SerialException as e:
            self.log_signal.emit(f"❌ Ошибка последовательного порта: {str(e)}")
            return False
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при отправке команды: {str(e)}")
            return False
    def get_thresholds(self):
        try:
            headers = {'X-Auth-Token': API_TOKEN}
            response = requests.get(THRESHOLDS_API_URL, headers=headers)
            if response.status_code == 200:
                data = response.json()
                current_time = time.time()
                global last_thresholds_print_time
                if current_time - last_thresholds_print_time >= THRESHOLDS_PRINT_INTERVAL:
                    self.log_signal.emit(f"📊 Получены пороговые значения от сервера")
                    last_thresholds_print_time = current_time
                return data
            elif response.status_code == 401:
                self.log_signal.emit("⛔ ОШИБКА АВТОРИЗАЦИИ ⛔")
                return None
            return None
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка получения порогов: {str(e)}")
            return None
class PlantPhotoThread(QThread):
    photo_taken_signal = pyqtSignal(np.ndarray, np.ndarray, dict)  
    log_signal = pyqtSignal(str)
    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.original_image = None
        self.detection_image = None
        self.color_percentages = {}
        self.detected_diseases = []
        self.detected_pests = []
    def run(self):
        try:
            self.log_signal.emit("📸 Делаем фото с камеры...")
            frame = self.take_photo()
            if frame is None:
                self.log_signal.emit("❌ Не удалось получить изображение с камеры")
                return
            self.original_image = frame.copy()
            height, width = frame.shape[:2]
            self.log_signal.emit("🔍 Анализируем изображение растения...")
            self.detect_plant(height, width)
            analysis = self.analyze_health()
            report_text = f"АНАЛИЗ СОСТОЯНИЯ РАСТЕНИЯ\nДата анализа: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nСОСТОЯНИЕ: {analysis['состояние']}\n\nРАСПРЕДЕЛЕНИЕ ЦВЕТОВ:\n{analysis['распределение цветов']}\n\nДЕТАЛИ АНАЛИЗА:\n{analysis['детали']}\n\nРЕКОМЕНДАЦИИ:\n{analysis['рекомендации']}\n"
            if self.upload_to_server(report_text):
                self.log_signal.emit("✅ Анализ растения успешно загружен на сервер")
            self.photo_taken_signal.emit(self.original_image, self.detection_image, analysis)
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при выполнении фотографирования: {str(e)}")
    def take_photo(self):
        """Сделать фото с камеры"""
        try:
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                self.log_signal.emit("❌ Ошибка подключения камеры")
                return None
            ret, frame = cap.read()
            cap.release()
            if not ret:
                self.log_signal.emit("❌ Ошибка получения изображения с камеры")
                return None
            return frame
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при фотографировании: {str(e)}")
            return None
    def detect_plant(self, height, width):
        """Обнаружение растения на изображении"""
        LEAF_COLORS = {
            "healthy_green": {"lower": np.array([35, 30, 30]), "upper": np.array([85, 255, 255]), "name": "здоровый зеленый"},
            "yellow": {"lower": np.array([20, 30, 30]), "upper": np.array([35, 255, 255]), "name": "желтый"},
            "brown": {"lower": np.array([10, 30, 10]), "upper": np.array([20, 255, 255]), "name": "коричневый"},
            "light_green": {"lower": np.array([35, 30, 30]), "upper": np.array([85, 100, 255]), "name": "светло-зеленый"}
        }
        try:
            self.height = height
            self.width = width
            hsv = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2HSV)
            self.detection_image = self.original_image.copy()
            total_mask = np.zeros((self.height, self.width), dtype=np.uint8)
            for color_name, color_range in LEAF_COLORS.items():
                mask = cv2.inRange(hsv, color_range["lower"], color_range["upper"])
                kernel = np.ones((3,3), np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                total_mask = cv2.bitwise_or(total_mask, mask)
            contours, _ = cv2.findContours(total_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            filtered_contours = []
            for contour in contours:
                if cv2.contourArea(contour) > 100:
                    filtered_contours.append(contour)
            cv2.drawContours(self.detection_image, filtered_contours, -1, (0, 255, 0), 2)
            self.plant_mask = np.zeros_like(total_mask)
            cv2.drawContours(self.plant_mask, filtered_contours, -1, 255, -1)
            plant_pixels = np.count_nonzero(self.plant_mask)
            if plant_pixels > 0:
                for color_name, color_range in LEAF_COLORS.items():
                    mask = cv2.inRange(hsv, color_range["lower"], color_range["upper"])
                    color_pixels = cv2.countNonZero(cv2.bitwise_and(mask, self.plant_mask))
                    self.color_percentages[color_name] = (color_pixels / plant_pixels) * 100
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при обнаружении растения: {str(e)}")
    def analyze_health(self):
        """Анализ здоровья растения"""
        DISEASES_DB = {
            "yellow_leaves": {"name": "Хлороз", "description": "Пожелтение листьев", "causes": ["Недостаток железа", "Переувлажнение", "Недостаток азота"], "solutions": ["Добавить железосодержащие удобрения", "Уменьшить полив", "Внести азотные удобрения"]},
            "brown_spots": {"name": "Грибковое заболевание", "description": "Коричневые пятна на листьях", "causes": ["Грибковая инфекция", "Избыточная влажность", "Плохая вентиляция"], "solutions": ["Обработать фунгицидами", "Улучшить вентиляцию", "Удалить пораженные листья"]}
        }
        PESTS_DB = {
            "aphids": {"name": "Тля", "description": "Мелкие насекомые на листьях и стеблях", "damage": "Высасывают сок из растения, вызывают деформацию листьев", "solutions": ["Обработать инсектицидами", "Использовать мыльный раствор", "Привлечь естественных хищников"]},
            "thrips": {"name": "Трипсы", "description": "Мелкие удлиненные насекомые", "damage": "Повреждают листья и цветы, переносят вирусы", "solutions": ["Обработать инсектицидами", "Использовать синие липкие ловушки", "Удалять сорняки"]}
        }
        try:
            self.detected_diseases = []
            self.detected_pests = []
            if self.color_percentages.get("yellow", 0) > 10:
                self.detected_diseases.append(DISEASES_DB["yellow_leaves"])
            if self.color_percentages.get("brown", 0) > 5:
                self.detected_diseases.append(DISEASES_DB["brown_spots"])
            if self.color_percentages.get("brown", 0) > 5:
                if self.color_percentages.get("yellow", 0) > 15:
                    self.detected_pests.append(PESTS_DB["aphids"])
                elif self.color_percentages.get("brown", 0) > 10:
                    self.detected_pests.append(PESTS_DB["thrips"])
            status = "нормальное"
            details = []
            recommendations = []
            if self.color_percentages.get("yellow", 0) > 10:
                status = "требует внимания"
                details.append("Обнаружено значительное пожелтение листьев")
                recommendations.append("Проверьте режим полива")
                recommendations.append("Проверьте уровень освещенности")
            if self.color_percentages.get("brown", 0) > 5:
                status = "требует внимания"
                details.append("Обнаружены коричневые участки на листьях")
                recommendations.append("Проверьте на наличие заболеваний")
                recommendations.append("Удалите поврежденные листья")
            for disease in self.detected_diseases:
                details.append(f"{disease['name']}: {disease['description']}")
                recommendations.extend(disease['solutions'])
            for pest in self.detected_pests:
                details.append(f"{pest['name']}: {pest['description']}")
                recommendations.extend(pest['solutions'])
            if not details:
                recommendations.append("Поддерживайте текущий режим ухода")
            LEAF_COLORS = {
                "healthy_green": {"name": "здоровый зеленый"},
                "yellow": {"name": "желтый"},
                "brown": {"name": "коричневый"},
                "light_green": {"name": "светло-зеленый"}
            }
            return {
                "состояние": status,
                "распределение цветов": "; ".join([f"{LEAF_COLORS[k]['name']}: {v:.1f}%" for k, v in self.color_percentages.items() if v > 1]),
                "детали": "; ".join(details) if details else "отклонений не выявлено",
                "рекомендации": "; ".join(recommendations)
            }
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при анализе здоровья растения: {str(e)}")
            return {
                "состояние": "ошибка анализа",
                "распределение цветов": "",
                "детали": f"Ошибка при анализе: {str(e)}",
                "рекомендации": "Попробуйте повторить анализ"
            }
    def upload_to_server(self, text="Анализ состояния растений"):
        """Загрузить фото на сервер"""
        if self.original_image is None or self.detection_image is None:
            self.log_signal.emit("❌ Нет изображений для загрузки на сервер")
            return False
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            orig_filename = f"farm_photo_{timestamp}.jpg"
            analysis_filename = f"farm_analysis_{timestamp}.jpg"
            cv2.imwrite(orig_filename, self.original_image)
            cv2.imwrite(analysis_filename, self.detection_image)
            if not os.path.exists(orig_filename) or not os.path.exists(analysis_filename):
                self.log_signal.emit("❌ Ошибка сохранения файлов")
                return False
            data = {
                'text': text, 
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                'has_analysis': 'true'
            }
            headers = {
                'X-Auth-Token': API_TOKEN
            }
            with open(orig_filename, 'rb') as orig_file, open(analysis_filename, 'rb') as analysis_file:
                files = {
                    'image': ('original.jpg', orig_file.read(), 'image/jpeg'),
                    'analysis_image': ('analysis.jpg', analysis_file.read(), 'image/jpeg')
                }
                response = requests.post(SERVER_URL, data=data, files=files, headers=headers)
                if response.status_code != 200:
                    self.log_signal.emit(f"❌ Ошибка сервера: {response.status_code}")
                    return False
                try:
                    response_data = response.json()
                    if not response_data.get('success'):
                        self.log_signal.emit(f"❌ Ошибка сервера: {response_data.get('message', 'Неизвестная ошибка')}")
                        return False
                    self.log_signal.emit(f"✅ Фото успешно загружено для пользователя с ID: {response_data.get('user_id')}")
                    return True
                except json.JSONDecodeError:
                    self.log_signal.emit("❌ Ошибка обработки ответа сервера")
                    return False
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка при загрузке на сервер: {str(e)}")
            return False
        finally:
            for filename in [orig_filename, analysis_filename]:
                if os.path.exists(filename):
                    try: os.remove(filename)
                    except: pass
class FarmControlApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ФитоДомик")
        app_icon = QIcon(ICON_FILE)
        self.setWindowIcon(app_icon)
        self.setMinimumSize(900, 850)
        self.serial_connection = None
        self.camera = None
        self.devices_thread = None
        self.photo_thread = None
        self.monitoring_thread = None
        self.api_token = API_TOKEN
        self.sensor_interval = 60
        self.photo_interval = 3600
        self.photo_mode = "Раз в день"
        self.photo_time1 = "13:00"
        self.photo_time2 = "16:00"
        self.next_photo_time = 0
        self.serial_port = SERIAL_PORT
        self.baud_rate = BAUD_RATE
        self.camera_index = CAMERA_INDEX
        self.log_text = None
        self.auto_connect = False
        self.load_settings()
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.create_ui()
    def create_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                font-size: 18px;
                font-weight: bold;
                padding: 10px 20px;
                margin: 2px;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background-color: 
                color: white;
            }
        """)
        self.main_layout.addWidget(self.tabs)
        self.monitoring_tab = QWidget()
        self.tabs.addTab(self.monitoring_tab, "Мониторинг")
        self.devices_tab = QWidget()
        self.tabs.addTab(self.devices_tab, "Управление")
        self.journal_tab = QWidget()
        self.tabs.addTab(self.journal_tab, "Журнал")
        self.setup_tab = QWidget()
        self.tabs.addTab(self.setup_tab, "Настройки")
        self.setup_monitoring_tab()
        self.setup_devices_tab()
        self.setup_journal_tab()
        self.setup_setup_tab()
        self.statusBar().hide()
        if hasattr(self, 'photo_interval_combo'):
            self.update_photo_time_inputs()
    def update_ui_from_settings(self):
        """Обновление UI из загруженных настроек и запись в журнал"""
        try:
            if os.path.exists(CONFIG_FILE):
                self.log("✅ Настройки успешно загружены из файла")
            else:
                self.log("ℹ️ Используются настройки по умолчанию")
            if hasattr(self, 'api_token_input') and self.api_token_input is not None:
                self.api_token_input.setText(self.api_token)
            if hasattr(self, 'port_combo') and self.port_combo is not None:
                self.port_combo.setCurrentText(self.serial_port)
            if hasattr(self, 'baud_combo') and self.baud_combo is not None:
                self.baud_combo.setCurrentText(str(self.baud_rate))
            if hasattr(self, 'camera_index_spin') and self.camera_index_spin is not None:
                self.camera_index_spin.setValue(self.camera_index)
            if hasattr(self, 'sensor_interval_spin') and self.sensor_interval_spin is not None:
                self.sensor_interval_spin.setValue(self.sensor_interval)
            if hasattr(self, 'photo_interval_combo') and self.photo_interval_combo is not None:
                mode_index = 0  
                for i in range(self.photo_interval_combo.count()):
                    if self.photo_interval_combo.itemText(i) == self.photo_mode:
                        mode_index = i
                        break
                self.photo_interval_combo.setCurrentIndex(mode_index)
                if hasattr(self, 'photo_time1_edit') and self.photo_time1_edit is not None:
                    self.photo_time1_edit.setText(self.photo_time1)
                if hasattr(self, 'photo_time2_edit') and self.photo_time2_edit is not None:
                    self.photo_time2_edit.setText(self.photo_time2)
                self.update_photo_time_inputs()
        except Exception as e:
            print(f"[LOG] Ошибка при обновлении UI из настроек: {str(e)}")
    def setup_monitoring_tab(self):
        layout = QVBoxLayout(self.monitoring_tab)
        image_group = QGroupBox("Состояние растения")
        image_group.setStyleSheet("QGroupBox { font-size: 22px; font-weight: bold; }")
        image_layout = QHBoxLayout()
        orig_image_layout = QVBoxLayout()
        orig_image_label = QLabel("Оригинальное изображение:")
        orig_image_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        orig_image_layout.addWidget(orig_image_label)
        self.image_label_orig = QLabel("Нет изображения")
        self.image_label_orig.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label_orig.setMinimumHeight(200)
        self.image_label_orig.setStyleSheet("background-color: #333333; color: white; border: 2px solid #555555; border-radius: 8px; font-size: 16px;")
        orig_image_layout.addWidget(self.image_label_orig)
        proc_image_layout = QVBoxLayout()
        proc_image_label = QLabel("Обработанное изображение:")
        proc_image_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        proc_image_layout.addWidget(proc_image_label)
        self.image_label = QLabel("Нет изображения")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(200)
        self.image_label.setStyleSheet("background-color: #333333; color: white; border: 2px solid #555555; border-radius: 8px; font-size: 16px;")
        proc_image_layout.addWidget(self.image_label)
        image_layout.addLayout(orig_image_layout)
        image_layout.addLayout(proc_image_layout)
        image_group.setLayout(image_layout)
        layout.addWidget(image_group)
        analysis_group = QGroupBox("Результаты анализа")
        analysis_group.setStyleSheet("QGroupBox { font-size: 22px; font-weight: bold; }")
        analysis_layout = QVBoxLayout()
        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setMaximumHeight(100)
        self.analysis_text.setStyleSheet("font-size: 16px; background-color: #333333; color: white; border: 2px solid #555555; border-radius: 8px;")
        analysis_layout.addWidget(self.analysis_text)
        system_btn_layout = QHBoxLayout()
        self.start_system_btn = QPushButton("ЗАПУСТИТЬ СИСТЕМУ")
        self.start_system_btn.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; background-color: #4CAF50; color: white; border-radius: 10px;")
        self.start_system_btn.setMinimumHeight(60)
        self.start_system_btn.clicked.connect(self.start_system)
        system_btn_layout.addWidget(self.start_system_btn)
        analysis_layout.addLayout(system_btn_layout)
        analysis_group.setLayout(analysis_layout)
        layout.addWidget(analysis_group)
        sensors_group = QGroupBox("Показания датчиков")
        sensors_group.setStyleSheet("QGroupBox { font-size: 22px; font-weight: bold; }")
        sensors_layout = QGridLayout()
        sensors_layout.setSpacing(10)
        card_style = """
            QFrame {
                background-color: #272727;
                border-radius: 8px;
                border: 1px solid #555555;
                padding: 8px;
            }
            QLabel {
                color: white;
            }
        """
        temp_card = QFrame()
        temp_card.setStyleSheet(card_style)
        temp_layout = QVBoxLayout(temp_card)
        temp_title = QHBoxLayout()
        temp_icon = QLabel("🌡️")
        temp_icon.setStyleSheet("font-size: 20px;")
        temp_name = QLabel("Температура")
        temp_name.setStyleSheet("font-size: 16px;")
        temp_title.addWidget(temp_icon)
        temp_title.addWidget(temp_name)
        temp_title.addStretch()
        temp_layout.addLayout(temp_title)
        self.temp_label = QLabel("-- °C")
        self.temp_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        temp_layout.addWidget(self.temp_label)
        sensors_layout.addWidget(temp_card, 0, 0)
        humidity_card = QFrame()
        humidity_card.setStyleSheet(card_style)
        humidity_layout = QVBoxLayout(humidity_card)
        humidity_title = QHBoxLayout()
        humidity_icon = QLabel("💧")
        humidity_icon.setStyleSheet("font-size: 20px;")
        humidity_name = QLabel("Влажность")
        humidity_name.setStyleSheet("font-size: 16px;")
        humidity_title.addWidget(humidity_icon)
        humidity_title.addWidget(humidity_name)
        humidity_title.addStretch()
        humidity_layout.addLayout(humidity_title)
        self.humidity_label = QLabel("-- %")
        self.humidity_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        humidity_layout.addWidget(self.humidity_label)
        sensors_layout.addWidget(humidity_card, 0, 1)
        soil_card = QFrame()
        soil_card.setStyleSheet(card_style)
        soil_layout = QVBoxLayout(soil_card)
        soil_title = QHBoxLayout()
        soil_icon = QLabel("🌱")
        soil_icon.setStyleSheet("font-size: 20px;")
        soil_name = QLabel("Влажность почвы")
        soil_name.setStyleSheet("font-size: 16px;")
        soil_title.addWidget(soil_icon)
        soil_title.addWidget(soil_name)
        soil_title.addStretch()
        soil_layout.addLayout(soil_title)
        self.soil_label = QLabel("-- %")
        self.soil_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        soil_layout.addWidget(self.soil_label)
        sensors_layout.addWidget(soil_card, 0, 2)
        co2_card = QFrame()
        co2_card.setStyleSheet(card_style)
        co2_layout = QVBoxLayout(co2_card)
        co2_title = QHBoxLayout()
        co2_icon = QLabel("🫧")
        co2_icon.setStyleSheet("font-size: 20px;")
        co2_name = QLabel("CO₂")
        co2_name.setStyleSheet("font-size: 16px;")
        co2_title.addWidget(co2_icon)
        co2_title.addWidget(co2_name)
        co2_title.addStretch()
        co2_layout.addLayout(co2_title)
        self.co2_label = QLabel("-- ppm")
        self.co2_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        co2_layout.addWidget(self.co2_label)
        sensors_layout.addWidget(co2_card, 0, 3)
        light_card = QFrame()
        light_card.setStyleSheet(card_style)
        light_layout = QVBoxLayout(light_card)
        light_title = QHBoxLayout()
        light_icon = QLabel("☀️")
        light_icon.setStyleSheet("font-size: 20px;")
        light_name = QLabel("Освещенность")
        light_name.setStyleSheet("font-size: 16px;")
        light_title.addWidget(light_icon)
        light_title.addWidget(light_name)
        light_title.addStretch()
        light_layout.addLayout(light_title)
        self.light_label = QLabel("-- lux")
        self.light_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        light_layout.addWidget(self.light_label)
        sensors_layout.addWidget(light_card, 1, 0)
        pressure_card = QFrame()
        pressure_card.setStyleSheet(card_style)
        pressure_layout = QVBoxLayout(pressure_card)
        pressure_title = QHBoxLayout()
        pressure_icon = QLabel("🌬️")
        pressure_icon.setStyleSheet("font-size: 20px;")
        pressure_name = QLabel("Давление")
        pressure_name.setStyleSheet("font-size: 16px;")
        pressure_title.addWidget(pressure_icon)
        pressure_title.addWidget(pressure_name)
        pressure_title.addStretch()
        pressure_layout.addLayout(pressure_title)
        self.pressure_label = QLabel("-- hPa")
        self.pressure_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        pressure_layout.addWidget(self.pressure_label)
        sensors_layout.addWidget(pressure_card, 1, 1)
        curtains_card = QFrame()
        curtains_card.setStyleSheet(card_style)
        curtains_layout = QVBoxLayout(curtains_card)
        curtains_title = QHBoxLayout()
        curtains_icon = QLabel("🪟")
        curtains_icon.setStyleSheet("font-size: 20px;")
        curtains_name = QLabel("Шторы")
        curtains_name.setStyleSheet("font-size: 16px;")
        curtains_title.addWidget(curtains_icon)
        curtains_title.addWidget(curtains_name)
        curtains_title.addStretch()
        curtains_layout.addLayout(curtains_title)
        self.curtains_label = QLabel("Неизвестно")
        self.curtains_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        curtains_layout.addWidget(self.curtains_label)
        sensors_layout.addWidget(curtains_card, 1, 2)
        led_card = QFrame()
        led_card.setStyleSheet(card_style)
        led_layout = QVBoxLayout(led_card)
        led_title = QHBoxLayout()
        led_icon = QLabel("💡")
        led_icon.setStyleSheet("font-size: 20px;")
        led_name = QLabel("Освещение")
        led_name.setStyleSheet("font-size: 16px;")
        led_title.addWidget(led_icon)
        led_title.addWidget(led_name)
        led_title.addStretch()
        led_layout.addLayout(led_title)
        self.led_label = QLabel("Неизвестно")
        self.led_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        led_layout.addWidget(self.led_label)
        sensors_layout.addWidget(led_card, 1, 3)
        sensors_group.setLayout(sensors_layout)
        layout.addWidget(sensors_group)
    def setup_devices_tab(self):
        layout = QVBoxLayout(self.devices_tab)
        led_group = QGroupBox("Управление лампой")
        led_group.setStyleSheet("QGroupBox { font-size: 22px; font-weight: bold; }")
        led_layout = QHBoxLayout()
        self.led_on_btn = QPushButton("Включить лампу")
        self.led_on_btn.clicked.connect(lambda: self.control_led(1))
        self.led_on_btn.setMinimumHeight(50)
        self.led_on_btn.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px; background-color: #4CAF50; color: white; border-radius: 8px;")
        led_layout.addWidget(self.led_on_btn)
        self.led_off_btn = QPushButton("Выключить лампу")
        self.led_off_btn.clicked.connect(lambda: self.control_led(0))
        self.led_off_btn.setMinimumHeight(50)
        self.led_off_btn.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px; background-color: #F44336; color: white; border-radius: 8px;")
        led_layout.addWidget(self.led_off_btn)
        led_group.setLayout(led_layout)
        layout.addWidget(led_group)
        curtains_group = QGroupBox("Управление шторами")
        curtains_group.setStyleSheet("QGroupBox { font-size: 22px; font-weight: bold; }")
        curtains_layout = QHBoxLayout()
        self.curtains_close_btn = QPushButton("Закрыть шторы")
        self.curtains_close_btn.clicked.connect(lambda: self.control_curtains(1))
        self.curtains_close_btn.setMinimumHeight(50)
        self.curtains_close_btn.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px; background-color: #4CAF50; color: white; border-radius: 8px;")
        curtains_layout.addWidget(self.curtains_close_btn)
        self.curtains_open_btn = QPushButton("Открыть шторы")
        self.curtains_open_btn.clicked.connect(lambda: self.control_curtains(0))
        self.curtains_open_btn.setMinimumHeight(50)
        self.curtains_open_btn.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px; background-color: #F44336; color: white; border-radius: 8px;")
        curtains_layout.addWidget(self.curtains_open_btn)
        curtains_group.setLayout(curtains_layout)
        layout.addWidget(curtains_group)
        photo_group = QGroupBox("Анализ растения")
        photo_group.setStyleSheet("QGroupBox { font-size: 22px; font-weight: bold; }")
        photo_layout = QVBoxLayout()
        self.photo_analysis_btn = QPushButton("📸 ФОТОАНАЛИЗ РАСТЕНИЯ")
        self.photo_analysis_btn.clicked.connect(self.analyze_plant)
        self.photo_analysis_btn.setMinimumHeight(60)
        self.photo_analysis_btn.setStyleSheet("font-size: 20px; font-weight: bold; padding: 10px; background-color: #4CAF50; color: white; border-radius: 10px;")
        photo_layout.addWidget(self.photo_analysis_btn)
        photo_group.setLayout(photo_layout)
        layout.addWidget(photo_group)
        layout.addStretch()
    def setup_journal_tab(self):
        layout = QVBoxLayout(self.journal_tab)
        log_group = QGroupBox("Журнал событий")
        log_group.setStyleSheet("QGroupBox { font-size: 22px; font-weight: bold; }")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-size: 18px;") 
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        buttons_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("Очистить журнал")
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.clear_log_btn.setMinimumHeight(45)
        self.clear_log_btn.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px; background-color: #4CAF50; color: white; border-radius: 8px;")
        buttons_layout.addWidget(self.clear_log_btn)
        self.save_log_btn = QPushButton("Сохранить журнал")
        self.save_log_btn.clicked.connect(self.save_log)
        self.save_log_btn.setMinimumHeight(45)
        self.save_log_btn.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px; background-color: #4CAF50; color: white; border-radius: 8px;")
        buttons_layout.addWidget(self.save_log_btn)
        layout.addLayout(buttons_layout)
    def setup_setup_tab(self):
        layout = QVBoxLayout(self.setup_tab)
        api_group = QGroupBox("Настройки API")
        api_layout = QFormLayout()
        api_layout.setSpacing(10)  
        token_layout = QHBoxLayout()
        self.api_token_input = QLineEdit()
        self.api_token_input.setStyleSheet("font-size: 16px; padding: 8px; border: 2px solid #4CAF50; border-radius: 4px;")
        self.api_token_input.setMinimumHeight(40)
        self.api_token_input.setText(self.api_token)
        token_layout.addWidget(self.api_token_input)
        self.paste_token_btn = QPushButton("📋")
        self.paste_token_btn.setToolTip("Вставить из буфера обмена")
        self.paste_token_btn.clicked.connect(self.paste_from_clipboard)
        self.paste_token_btn.setMinimumHeight(30)
        self.paste_token_btn.setMinimumWidth(30)
        self.paste_token_btn.setMaximumWidth(30)
        self.paste_token_btn.setStyleSheet("font-size: 12px; font-weight: bold; padding: 0px; background-color: #4CAF50; color: white; border-radius: 4px;")
        token_layout.addWidget(self.paste_token_btn)
        api_layout.addRow(QLabel("API токен:"), token_layout)
        buttons_layout = QVBoxLayout()  
        buttons_layout.setSpacing(8)  
        self.save_api_btn = QPushButton("Сохранить токен")
        self.save_api_btn.clicked.connect(self.save_api_token)
        self.save_api_btn.setMinimumHeight(32)
        self.save_api_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px; background-color: #4CAF50; color: white; border-radius: 6px;")
        buttons_layout.addWidget(self.save_api_btn)
        self.get_token_btn = QPushButton("Получить токен")
        self.get_token_btn.clicked.connect(self.open_token_site)
        self.get_token_btn.setMinimumHeight(32)
        self.get_token_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px; background-color: #4CAF50; color: white; border-radius: 6px;")
        buttons_layout.addWidget(self.get_token_btn)
        api_layout.addRow("", buttons_layout)
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
        arduino_group = QGroupBox("Настройки Arduino")
        arduino_layout = QFormLayout()
        arduino_layout.setSpacing(10)  
        self.port_combo = QComboBox()
        self.port_combo.addItems(['COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'COM10'])
        self.port_combo.setCurrentText(self.serial_port)
        self.port_combo.setStyleSheet("""
            QComboBox { 
                font-size: 16px; 
                padding: 8px; 
                border: 2px solid #4CAF50; 
                border-radius: 4px; 
            } 
            QComboBox::drop-down { 
                subcontrol-origin: content;
                subcontrol-position: right;
                width: 0px;
                border: none;
            }
            QComboBox QAbstractItemView {
                font-size: 16px;
                border: 2px solid #4CAF50;
                selection-background-color: #4CAF50;
                selection-color: white;
            }
        """)
        self.port_combo.setMinimumHeight(36)
        arduino_layout.addRow(QLabel("COM порт:"), self.port_combo)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(['9600', '19200', '38400', '57600', '115200'])
        self.baud_combo.setCurrentText(str(self.baud_rate))
        self.baud_combo.setStyleSheet("""
            QComboBox { 
                font-size: 16px; 
                padding: 8px; 
                border: 2px solid #4CAF50; 
                border-radius: 4px; 
            } 
            QComboBox::drop-down { 
                subcontrol-origin: content;
                subcontrol-position: right;
                width: 0px;
                border: none;
            }
            QComboBox QAbstractItemView {
                font-size: 16px;
                border: 2px solid #4CAF50;
                selection-background-color: #4CAF50;
                selection-color: white;
            }
        """)
        self.baud_combo.setMinimumHeight(36)
        arduino_layout.addRow(QLabel("Скорость:"), self.baud_combo)
        self.connect_arduino_btn = QPushButton("Подключить Arduino")
        self.connect_arduino_btn.clicked.connect(self.connect_to_arduino)
        self.connect_arduino_btn.setMinimumHeight(32)
        self.connect_arduino_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px; background-color: #4CAF50; color: white; border-radius: 6px;")
        arduino_layout.addRow("", self.connect_arduino_btn)
        arduino_group.setLayout(arduino_layout)
        layout.addWidget(arduino_group)
        camera_group = QGroupBox("Настройки камеры")
        camera_layout = QFormLayout()
        camera_layout.setSpacing(10)  
        self.camera_index_spin = QSpinBox()
        self.camera_index_spin.setRange(0, 10)
        self.camera_index_spin.setValue(self.camera_index)
        self.camera_index_spin.setStyleSheet("font-size: 16px; padding: 8px; border: 2px solid #4CAF50; border-radius: 4px;")
        self.camera_index_spin.setMinimumHeight(36)
        self.camera_index_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)  
        camera_layout.addRow(QLabel("Индекс:"), self.camera_index_spin)
        self.test_camera_btn = QPushButton("Проверить камеру")
        self.test_camera_btn.clicked.connect(self.test_camera)
        self.test_camera_btn.setMinimumHeight(32)
        self.test_camera_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px; background-color: #4CAF50; color: white; border-radius: 6px;")
        camera_layout.addRow("", self.test_camera_btn)
        camera_group.setLayout(camera_layout)
        layout.addWidget(camera_group)
        intervals_group = QGroupBox("Настройки интервалов")
        intervals_layout = QFormLayout()
        intervals_layout.setSpacing(10)  
        self.sensor_interval_spin = QSpinBox()
        self.sensor_interval_spin.setRange(1, 3600)
        self.sensor_interval_spin.setValue(self.sensor_interval)
        self.sensor_interval_spin.setSuffix(" сек.")
        self.sensor_interval_spin.setStyleSheet("font-size: 16px; padding: 8px; border: 2px solid #4CAF50; border-radius: 4px;")
        self.sensor_interval_spin.setMinimumHeight(36)
        self.sensor_interval_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)  
        intervals_layout.addRow(QLabel("Опрос:"), self.sensor_interval_spin)
        photo_layout = QVBoxLayout()
        self.photo_interval_combo = QComboBox()
        photo_modes = [
            "Раз в день", 
            "Два раза в день", 
            "Каждые 10 минут (тест)"
        ]
        for mode in photo_modes:
            self.photo_interval_combo.addItem(mode)
        self.photo_interval_combo.setStyleSheet("""
            QComboBox { 
                font-size: 16px; 
                padding: 8px; 
                border: 2px solid #4CAF50; 
                border-radius: 4px; 
            }
            QComboBox::drop-down { 
                subcontrol-origin: content;
                subcontrol-position: right;
                width: 0px;
                border: none;
            }
            QComboBox QAbstractItemView {
                font-size: 16px;
                border: 2px solid #4CAF50;
                selection-background-color: #4CAF50;
                selection-color: white;
            }
        """)
        self.photo_interval_combo.setMinimumHeight(36)
        photo_layout.addWidget(self.photo_interval_combo)
        self.photo_time_container = QWidget()
        time_layout = QVBoxLayout(self.photo_time_container)
        time_layout.setContentsMargins(0, 5, 0, 0)
        time1_layout = QHBoxLayout()
        self.photo_time1_label = QLabel("Время:")
        self.photo_time1_label.setStyleSheet("font-size: 14px;")
        time1_layout.addWidget(self.photo_time1_label)
        self.photo_time1_edit = QLineEdit("13:00")
        self.photo_time1_edit.setStyleSheet("font-size: 14px; padding: 5px; border: 1px solid #4CAF50; border-radius: 4px;")
        self.photo_time1_edit.setPlaceholderText("ЧЧ:ММ")
        time1_layout.addWidget(self.photo_time1_edit)
        time_layout.addLayout(time1_layout)
        time2_layout = QHBoxLayout()
        self.photo_time2_label = QLabel("Второе время:")
        self.photo_time2_label.setStyleSheet("font-size: 14px;")
        time2_layout.addWidget(self.photo_time2_label)
        self.photo_time2_edit = QLineEdit("16:00")
        self.photo_time2_edit.setStyleSheet("font-size: 14px; padding: 5px; border: 1px solid #4CAF50; border-radius: 4px;")
        self.photo_time2_edit.setPlaceholderText("ЧЧ:ММ")
        time2_layout.addWidget(self.photo_time2_edit)
        time_layout.addLayout(time2_layout)
        photo_layout.addWidget(self.photo_time_container)
        self.photo_interval_combo.currentIndexChanged.connect(self.update_photo_time_inputs)
        intervals_layout.addRow(QLabel("Фото:"), photo_layout)
        self.save_intervals_btn = QPushButton("Сохранить интервалы")
        self.save_intervals_btn.clicked.connect(self.save_intervals)
        self.save_intervals_btn.setMinimumHeight(45)
        self.save_intervals_btn.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px; background-color: #4CAF50; color: white; border-radius: 8px;")
        intervals_layout.addRow("", self.save_intervals_btn)
        intervals_group.setLayout(intervals_layout)
        layout.addWidget(intervals_group)
        groupStyle = "QGroupBox { font-size: 18px; font-weight: bold; }"
        api_group.setStyleSheet(groupStyle)
        arduino_group.setStyleSheet(groupStyle)
        camera_group.setStyleSheet(groupStyle)
        intervals_group.setStyleSheet(groupStyle)
        for label in self.findChildren(QLabel):
            label.setStyleSheet("font-size: 16px;")
        layout.addStretch()
        self.update_ui_from_settings()
    def test_camera(self):
        """Проверяет подключение к камере"""
        global CAMERA_INDEX
        CAMERA_INDEX = self.camera_index_spin.value()
        self.camera_index = CAMERA_INDEX
        try:
            cap = cv2.VideoCapture(CAMERA_INDEX)
            if not cap.isOpened():
                QMessageBox.critical(self, "Ошибка", f"Не удалось подключиться к камере с индексом {CAMERA_INDEX}")
                return
            ret, frame = cap.read()
            cap.release()
            if not ret:
                QMessageBox.critical(self, "Ошибка", "Не удалось получить изображение с камеры")
                return
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).rgbSwapped()
            self.image_label_orig.setPixmap(QPixmap.fromImage(q_img).scaled(
                self.image_label_orig.width(), self.image_label_orig.height(), 
                Qt.AspectRatioMode.KeepAspectRatio
            ))
            self.save_settings()
            QMessageBox.information(self, "Камера", f"Камера с индексом {CAMERA_INDEX} успешно подключена!")
            self.log(f"✅ Камера с индексом {CAMERA_INDEX} успешно подключена!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при подключении к камере: {str(e)}")
            self.log(f"❌ Ошибка при подключении к камере: {str(e)}")
    def start_system(self):
        if hasattr(self, 'sensor_thread') and self.sensor_thread.isRunning():
            self.stop_system()
            return
        if not self.check_connection():
            try:
                self.log("🔄 Попытка автоматического подключения...")
                self.serial_connection = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
                self.log(f"✅ Успешное автоматическое подключение к Arduino на порту {self.serial_port}")
            except Exception as e:
                self.log(f"❌ Ошибка автоподключения: {str(e)}")
                QMessageBox.warning(self, "Ошибка", "Нет подключения к устройству!")
                return
        self.log("🚀 Система запущена!")
        self.sensor_thread = SensorMonitoringThread(self.serial_connection, self.sensor_interval)
        self.sensor_thread.update_signal.connect(self.update_sensor_display)
        self.sensor_thread.log_signal.connect(self.log)
        self.sensor_thread.start()
        self.devices_thread = DevicesControlThread(self.serial_connection)
        self.devices_thread.update_signal.connect(self.update_sensor_display)
        self.devices_thread.log_signal.connect(self.log)
        self.devices_thread.start()
        self.calculate_next_photo_time()
        self.photo_thread_active = True
        self.photo_thread_runner = threading.Thread(target=self.photo_thread_function, daemon=True)
        self.photo_thread_runner.start()
        self.start_system_btn.setText("ОСТАНОВИТЬ СИСТЕМУ")
        self.start_system_btn.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; background-color: #F44336; color: white; border-radius: 10px;")
        self.save_api_btn.setEnabled(False)
        self.connect_arduino_btn.setEnabled(False)
        self.save_intervals_btn.setEnabled(False)
        self.auto_connect = True
        self.save_settings()
    def stop_system(self):
        if hasattr(self, 'sensor_thread') and self.sensor_thread.isRunning():
            self.sensor_thread.running = False
            self.sensor_thread.wait()
        if hasattr(self, 'devices_thread') and self.devices_thread.isRunning():
            self.devices_thread.running = False
            self.devices_thread.wait()
        self.photo_thread_active = False
        self.start_system_btn.setText("ЗАПУСТИТЬ СИСТЕМУ")
        self.start_system_btn.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; background-color: #4CAF50; color: white; border-radius: 10px;")
        self.save_api_btn.setEnabled(True)
        self.connect_arduino_btn.setEnabled(True)
        self.save_intervals_btn.setEnabled(True)
        self.log("Система остановлена!")
        self.auto_connect = False
        self.save_settings()
    def photo_thread_function(self):
        """Функция для выполнения периодического фотографирования"""
        log_message = "🧵 Запущен поток периодического фотографирования: "
        if self.photo_mode == "Каждые 10 минут (тест)":
            log_message += f"режим = {self.photo_mode}"
        elif self.photo_mode == "Раз в день":
            log_message += f"режим = {self.photo_mode} в {self.photo_time1}"
        else:  
            log_message += f"режим = {self.photo_mode} в {self.photo_time1} и {self.photo_time2}"
        self.log(log_message)
        self.calculate_next_photo_time()
        last_photo_time = time.time()
        last_photo_seconds = 0  
        current_day = datetime.now().day
        photos_taken_today = {}
        while self.photo_thread_active:
            try:
                current_time = time.time()
                now = datetime.now()
                if now.day != current_day:
                    current_day = now.day
                    photos_taken_today = {}
                    self.log(f"Новый день ({now.strftime('%Y-%m-%d')}). Сбрасываем информацию о сделанных фото.")
                if self.photo_mode == "Каждые 10 минут (тест)":
                    if current_time - last_photo_time >= self.photo_interval:
                        self.log(f"Делаем тестовое фото (прошло {int((current_time - last_photo_time))} секунд)")
                        self.take_scheduled_photo()
                        last_photo_time = time.time()
                else:
                    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
                    time_points = []
                    time_names = {}  
                    if self.photo_mode == "Раз в день":
                        try:
                            hours, minutes = map(int, self.photo_time1.split(':'))
                            seconds = hours * 3600 + minutes * 60
                            time_points.append(seconds)
                            time_names[seconds] = self.photo_time1
                        except ValueError:
                            self.log(f"❌ Ошибка формата времени 1: {self.photo_time1}")
                    else:  
                        for idx, time_str in enumerate([self.photo_time1, self.photo_time2]):
                            try:
                                hours, minutes = map(int, time_str.split(':'))
                                seconds = hours * 3600 + minutes * 60
                                time_points.append(seconds)
                                time_names[seconds] = time_str
                            except ValueError:
                                self.log(f"❌ Ошибка формата времени {idx+1}: {time_str}")
                    time_points.sort()
                    for seconds in time_points:
                        time_key = time_names[seconds]  
                        if time_key in photos_taken_today and photos_taken_today[time_key]:
                            continue  
                        if abs(current_seconds - seconds) <= 30:
                            self.log(f"Наступило запланированное время для фото: {time_names[seconds]}")
                            self.take_scheduled_photo()
                            last_photo_time = time.time()
                            last_photo_seconds = current_seconds
                            photos_taken_today[time_key] = True
                            break  
                time.sleep(5)  
            except Exception as e:
                self.log(f"❌ Ошибка в потоке фотографирования: {str(e)}")
                time.sleep(10)  
    def take_scheduled_photo(self):
        """Делает фото по расписанию"""
        self.log("\n=== Выполнение запланированного фотографирования ===")
        photo_thread = PlantPhotoThread(CAMERA_INDEX)
        photo_thread.log_signal.connect(self.log)
        photo_thread.photo_taken_signal.connect(self.handle_photo_taken)
        photo_thread.start()
        photo_thread.wait()  
    def update_sensor_display(self):
        """Обновляет отображение данных с датчиков"""
        global last_temperature, last_humidity, last_soil_moisture, last_light_level, last_co2, last_pressure
        global last_led_state, last_curtains_state
        self.temp_label.setText(f"{last_temperature:.1f} °C")
        self.humidity_label.setText(f"{last_humidity:.1f} %")
        self.soil_label.setText(f"{last_soil_moisture:.1f} %")
        self.light_label.setText(f"{last_light_level:.1f} lux")
        self.co2_label.setText(f"{last_co2:.0f} ppm")
        self.pressure_label.setText(f"{last_pressure:.1f} hPa")
        led_status = "Неизвестно"
        if last_led_state is not None:
            led_status = "Включено" if last_led_state == 1 else "Выключено"
        self.led_label.setText(led_status)
        curtains_status = "Неизвестно"
        if last_curtains_state is not None:
            curtains_status = "Закрыты" if last_curtains_state == 1 else "Открыты"
        self.curtains_label.setText(curtains_status)
    def handle_photo_taken(self, original_image, detection_image, analysis):
        """Обрабатывает сигнал о сделанном фото и анализе"""
        height, width, channel = original_image.shape
        bytes_per_line = 3 * width
        q_img_orig = QImage(original_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).rgbSwapped()
        pixmap_orig = QPixmap.fromImage(q_img_orig)
        self.image_label_orig.setPixmap(pixmap_orig.scaled(
            self.image_label_orig.width(), self.image_label_orig.height(), 
            Qt.AspectRatioMode.KeepAspectRatio
        ))
        height, width, channel = detection_image.shape
        bytes_per_line = 3 * width
        q_img = QImage(detection_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap.scaled(
            self.image_label.width(), self.image_label.height(), 
            Qt.AspectRatioMode.KeepAspectRatio
        ))
        self.analysis_text.clear()
        self.analysis_text.append(f"СОСТОЯНИЕ: {analysis['состояние']} | ЦВЕТА: {analysis['распределение цветов']}")
        self.analysis_text.append(f"ДЕТАЛИ: {analysis['детали']}")
        self.analysis_text.append(f"РЕКОМЕНДАЦИИ: {analysis['рекомендации']}")
        self.log("✅ Анализ растения успешно завершен")
    def save_api_token(self):
        global API_TOKEN
        token = self.api_token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "Предупреждение", "API токен не может быть пустым!")
            return
        API_TOKEN = token
        self.api_token = token
        self.log("API токен сохранен")
        self.save_settings()
        QMessageBox.information(self, "API Токен", "API токен успешно сохранен!")
    def connect_to_arduino(self):
        global SERIAL_PORT, BAUD_RATE
        SERIAL_PORT = self.port_combo.currentText()
        BAUD_RATE = int(self.baud_combo.currentText())
        self.serial_port = SERIAL_PORT
        self.baud_rate = BAUD_RATE
        try:
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                self.log("Соединение с Arduino закрыто")
            self.serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            self.log(f"✅ Подключено к Arduino на порту {SERIAL_PORT}")
            self.save_settings()
            QMessageBox.information(self, "Подключение", f"Успешное подключение к Arduino на порту {SERIAL_PORT}")
            self.start_arduino_reading()
        except serial.SerialException as e:
            self.log(f"❌ Ошибка подключения к Arduino: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось подключиться к Arduino: {str(e)}")
    def save_intervals(self):
        old_photo_mode = self.photo_mode
        old_photo_time1 = self.photo_time1
        old_photo_time2 = self.photo_time2
        self.sensor_interval = self.sensor_interval_spin.value()
        self.photo_mode = self.photo_interval_combo.currentText()
        if self.photo_mode == "Каждые 10 минут (тест)":
            self.photo_interval = 600  
        else:
            self.photo_time1 = self.photo_time1_edit.text().strip()
            if not self.is_valid_time_format(self.photo_time1):
                QMessageBox.warning(self, "Ошибка", "Некорректный формат времени 1. Используйте формат ЧЧ:ММ")
                return
            if self.photo_mode == "Два раза в день":
                self.photo_time2 = self.photo_time2_edit.text().strip()
                if not self.is_valid_time_format(self.photo_time2):
                    QMessageBox.warning(self, "Ошибка", "Некорректный формат времени 2. Используйте формат ЧЧ:ММ")
                    return
        photo_settings_changed = (
            old_photo_mode != self.photo_mode or 
            old_photo_time1 != self.photo_time1 or 
            old_photo_time2 != self.photo_time2
        )
        self.save_settings()
        self.calculate_next_photo_time()
        message = f"✅ Интервалы обновлены: датчики = {self.sensor_interval} сек."
        if self.photo_mode == "Каждые 10 минут (тест)":
            message += f", фото = {self.photo_mode}"
        elif self.photo_mode == "Раз в день":
            message += f", фото = {self.photo_mode} в {self.photo_time1}"
        else:  
            message += f", фото = {self.photo_mode} в {self.photo_time1} и {self.photo_time2}"
        self.log(message)
        if hasattr(self, 'photo_thread_active') and self.photo_thread_active and photo_settings_changed:
            self.log("Перезапуск потока фотографирования с новыми настройками...")
            self.photo_thread_active = False
            time.sleep(1)
            self.photo_thread_active = True
            self.photo_thread_runner = threading.Thread(target=self.photo_thread_function, daemon=True)
            self.photo_thread_runner.start()
        QMessageBox.information(self, "Интервалы", "Интервалы успешно обновлены!")
    def is_valid_time_format(self, time_str):
        """Проверяет валидность формата времени ЧЧ:ММ"""
        try:
            if not time_str or len(time_str) < 3 or ":" not in time_str:
                return False
            hours, minutes = map(int, time_str.split(':'))
            return 0 <= hours < 24 and 0 <= minutes < 60
        except ValueError:
            return False
    def calculate_next_photo_time(self):
        """Вычисляет секунды с начала дня до следующего запланированного фото"""
        if self.photo_mode == "Каждые 10 минут (тест)":
            self.next_photo_time = 0
            return
        current_time = datetime.now()
        if self.photo_mode == "Раз в день":
            time_points = [self.photo_time1]
        else:  
            time_points = [self.photo_time1, self.photo_time2]
        seconds_per_time = []
        for time_str in time_points:
            try:
                hours, minutes = map(int, time_str.split(':'))
                seconds = hours * 3600 + minutes * 60
                seconds_per_time.append(seconds)
            except ValueError:
                seconds_per_time.append(current_time.hour * 3600 + current_time.minute * 60)
        seconds_per_time.sort()
        current_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        for seconds in seconds_per_time:
            if seconds > current_seconds:
                self.next_photo_time = seconds
                return
        self.next_photo_time = seconds_per_time[0]
    def clear_log(self):
        self.log_text.clear()
    def save_log(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Сохранить журнал", "", "Текстовые файлы (*.txt);;Все файлы (*)")
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                QMessageBox.information(self, "Сохранение журнала", "Журнал успешно сохранен!")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить журнал: {str(e)}")
    def analyze_plant(self):
        self.photo_thread = PlantPhotoThread(CAMERA_INDEX)
        self.photo_thread.photo_taken_signal.connect(self.handle_photo_taken)
        self.photo_thread.log_signal.connect(self.log)
        self.photo_thread.start()
    def control_led(self, state):
        if not self.serial_connection or not self.serial_connection.is_open:
            QMessageBox.warning(self, "Предупреждение", "Arduino не подключен!")
            return
        try:
            global last_led_state
            command = f"LED:{1 if state == 1 else 0}\n"
            self.serial_connection.write(command.encode())
            status_text = "включена" if state == 1 else "выключена"
            self.log(f"💡 Лампа: {status_text}")
            last_led_state = state
            self.update_sensor_display()
            QMessageBox.information(self, "Лампа", f"Лампа успешно {status_text}!")
        except Exception as e:
            self.log(f"❌ Ошибка при управлении лампой: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось управлять лампой: {str(e)}")
    def control_curtains(self, state):
        if not self.serial_connection or not self.serial_connection.is_open:
            QMessageBox.warning(self, "Предупреждение", "Arduino не подключен!")
            return
        try:
            global last_curtains_state
            command = f"CURTAINS:{1 if state == 1 else 0}\n"
            self.serial_connection.write(command.encode())
            status_text = "закрыты" if state == 1 else "открыты"
            self.log(f"🪟 Шторы: {status_text}")
            last_curtains_state = state
            self.update_sensor_display()
            QMessageBox.information(self, "Шторы", f"Шторы успешно {status_text}!")
        except Exception as e:
            self.log(f"❌ Ошибка при управлении шторами: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось управлять шторами: {str(e)}")
    def apply_thresholds(self):
        pass
    def should_log_message(self, message):
        """Проверяет, нужно ли записывать сообщение в журнал"""
        if message.startswith("❌") or "ошибка" in message.lower() or "ERROR" in message.upper():
            return True
        important_messages = [
            "API токен сохранен",
            "Подключено к Arduino",
            "Камера с индексом",
            "Интервалы обновлены",
            "Система запущена",
            "Система остановлена",
            "ID записи:",
            "Температура воздуха:",
            "Влажность воздуха:",
            "Влажность почвы:",
            "Уровень освещенности:",
            "CO₂ уровень:",
            "Атм. давление:",
            "Лампа:",
            "Шторы:",
            "Делаем фото с камеры",
            "Анализируем изображение",
            "Фото успешно загружено",
            "Анализ растения успешно",
            "Настройки успешно",
            "Используются настройки"
        ]
        for important_msg in important_messages:
            if important_msg in message:
                return True
        if "────────────────────────────────────" in message:
            return True
        return False
    def log(self, message):
        """Добавляет сообщение в журнал"""
        if not hasattr(self, 'log_text') or self.log_text is None:
            print(f"[LOG] {message}")
            return
        if hasattr(self, 'should_log_message'):
            if not self.should_log_message(message):
                return
        if message.startswith("📅"):
            formatted_message = message
        else:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            formatted_message = f"{timestamp} - {message}"
        self.log_text.append(formatted_message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    def start_arduino_reading(self):
        """Запускает чтение данных с Arduino"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_sensor_display)
        self.update_timer.start(1000)  
    def check_connection(self):
        """Проверяет наличие подключения к Arduino"""
        if not hasattr(self, 'serial_connection') or not self.serial_connection or not self.serial_connection.is_open:
            return False
        return True
    def open_token_site(self):
        """Открывает сайт для получения API токена"""
        import webbrowser
        webbrowser.open("https://farm429.online/get_token.php")
        self.log("🌐 Открыт сайт для получения API токена")
    def paste_from_clipboard(self):
        """Вставляет содержимое буфера обмена в поле API токена"""
        clipboard = QApplication.clipboard()
        self.api_token_input.setText(clipboard.text())
        self.log("📋 Текст вставлен из буфера обмена")
    def load_settings(self):
        """Загрузка настроек из JSON файла"""
        try:
            if not os.path.exists(CONFIG_FILE):
                print("[LOG] Файл настроек не найден, будут использованы значения по умолчанию")
                return
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                global API_TOKEN, SERIAL_PORT, BAUD_RATE, CAMERA_INDEX
                if 'api_token' in settings:
                    self.api_token = settings['api_token']
                    API_TOKEN = settings['api_token']
                if 'serial_port' in settings:
                    self.serial_port = settings['serial_port']
                    SERIAL_PORT = settings['serial_port']
                if 'baud_rate' in settings:
                    self.baud_rate = settings['baud_rate']
                    BAUD_RATE = settings['baud_rate']
                if 'camera_index' in settings:
                    self.camera_index = settings['camera_index']
                    CAMERA_INDEX = settings['camera_index']
                if 'sensor_interval' in settings:
                    self.sensor_interval = settings['sensor_interval']
                if 'photo_interval' in settings:
                    self.photo_interval = settings['photo_interval']
                if 'photo_mode' in settings:
                    self.photo_mode = settings['photo_mode']
                if 'photo_time1' in settings:
                    self.photo_time1 = settings['photo_time1']
                if 'photo_time2' in settings:
                    self.photo_time2 = settings['photo_time2']
                if 'auto_connect' in settings:
                    self.auto_connect = settings['auto_connect']
                print("[LOG] Настройки успешно загружены")
        except Exception as e:
            print(f"[LOG] Ошибка при загрузке настроек: {str(e)}")
    def save_settings(self):
        """Сохранение настроек в JSON файл"""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            settings = {
                'api_token': self.api_token,
                'serial_port': self.serial_port,
                'baud_rate': self.baud_rate,
                'camera_index': self.camera_index,
                'sensor_interval': self.sensor_interval,
                'photo_mode': self.photo_mode,
                'auto_connect': self.auto_connect
            }
            if self.photo_mode == "Каждые 10 минут (тест)":
                settings['photo_interval'] = 600  
            elif self.photo_mode == "Раз в день":
                settings['photo_time1'] = self.photo_time1
            else:  
                settings['photo_time1'] = self.photo_time1
                settings['photo_time2'] = self.photo_time2
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
            self.log("✅ Настройки успешно сохранены")
            return True
        except Exception as e:
            self.log(f"❌ Ошибка при сохранении настроек: {str(e)}")
            return False
    def update_photo_time_inputs(self):
        """Обновляет видимость полей ввода времени в зависимости от режима фотографирования"""
        current_mode = self.photo_interval_combo.currentText()
        if current_mode == "Каждые 10 минут (тест)":
            self.photo_time_container.setVisible(False)
        else:
            self.photo_time_container.setVisible(True)
            self.photo_time2_label.setVisible(current_mode == "Два раза в день")
            self.photo_time2_edit.setVisible(current_mode == "Два раза в день")
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app_icon = QIcon(ICON_FILE)
    app.setWindowIcon(app_icon)
    window = FarmControlApp()
    window.show()
    sys.exit(app.exec())
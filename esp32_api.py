from flask import Flask, request, jsonify
from database import log_event, log_alert, get_current_status
from datetime import datetime
import requests
import os

# Окремий Flask додаток для API
esp32_app = Flask(__name__)

# Telegram бот для сповіщень
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')

def send_telegram_alert(message):
    """Надсилання сповіщення в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=data)
    except Exception as e:
        print(f"Помилка сповіщення: {e}")

@esp32_app.route('/api/gate/status', methods=['POST'])
def gate_status():
    """
    API для ESP32: отримання статусу воріт
    Очікує JSON: {"gate_id": 1, "status": "open/close"}
    """
    try:
        data = request.get_json()
        gate_id = data.get('gate_id')
        status = data.get('status')  # 'open' або 'close'
        
        if not gate_id or not status:
            return jsonify({"error": "Missing gate_id or status"}), 400
        
        if status == 'open':
            # Логуємо відкриття
            log_event(gate_id, 'open', 'esp32')
            send_telegram_alert(f"🔓 *Ворота №{gate_id}* відкриті (ESP32)")
            return jsonify({"status": "ok", "message": f"Gate {gate_id} opened"}), 200
        
        elif status == 'close':
            # Логуємо закриття
            log_event(gate_id, 'close', 'esp32')
            return jsonify({"status": "ok", "message": f"Gate {gate_id} closed"}), 200
        
        else:
            return jsonify({"error": "Invalid status"}), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@esp32_app.route('/api/gate/alert', methods=['POST'])
def gate_alert():
    """
    API для ESP32: сповіщення про аварію
    Очікує JSON: {"gate_id": 1, "reason": "open_too_long"}
    """
    try:
        data = request.get_json()
        gate_id = data.get('gate_id')
        reason = data.get('reason', 'unknown')
        
        log_event(gate_id, 'alert', 'esp32')
        log_alert(gate_id, datetime.now().isoformat())
        
        # Термінове сповіщення
        send_telegram_alert(f"🚨 *КРИТИЧНА АВАРІЯ!*\nВорота №{gate_id}\nПричина: {reason}\n⚠️ ПОТРІБНЕ ВТРУЧАННЯ!")
        
        return jsonify({"status": "ok", "message": "Alert sent"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@esp32_app.route('/api/status/all', methods=['GET'])
def get_all_status():
    """Отримання статусу всіх воріт (для ESP32)"""
    status = get_current_status()
    return jsonify(status), 200

# Для тестування ESP32 (відправити тестовий запит)
@esp32_app.route('/api/test', methods=['GET'])
def test_api():
    return jsonify({
        "status": "ok",
        "message": "API для ESP32 працює",
        "endpoints": [
            "POST /api/gate/status - оновити статус",
            "POST /api/gate/alert - сповіщення про аварію",
            "GET /api/status/all - отримати всі статуси"
        ]
    }), 200

import telebot
import time
import threading
import random
import sqlite3
import json
import requests
import os
from datetime import datetime, timedelta
from telebot import types
from flask import Flask, request, jsonify

# ===== КОНФІГУРАЦІЯ =====
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8670900193:AAF3c82nGP-6b5F25NM_RHYekoVqMQ2un7c')
CHAT_ID = os.environ.get('CHAT_ID', '209403052')
MAX_OPEN_TIME_SEC = int(os.environ.get('MAX_OPEN_TIME', '60'))
TOTAL_GATES = int(os.environ.get('TOTAL_GATES', '50'))

# Перевірка наявності токена
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не знайдено! Додайте змінну оточення на Render.com")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ===== БАЗА ДАНИХ =====
DB_PATH = '/var/data/gates.db'

# Створення папки для БД
os.makedirs('/var/data', exist_ok=True)

def init_db():
    """Ініціалізація бази даних"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблиця подій відкриття/закриття
    c.execute('''CREATE TABLE IF NOT EXISTS gate_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gate_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        source TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        duration INTEGER,
        alert_sent BOOLEAN DEFAULT FALSE
    )''')
    
    # Таблиця аварій
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gate_id INTEGER NOT NULL,
        start_time DATETIME NOT NULL,
        end_time DATETIME,
        duration INTEGER,
        resolved_by TEXT,
        resolved_at DATETIME
    )''')
    
    # Таблиця щоденної статистики
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
        date DATE PRIMARY KEY,
        total_opens INTEGER DEFAULT 0,
        total_alerts INTEGER DEFAULT 0,
        total_duration INTEGER DEFAULT 0,
        avg_duration INTEGER DEFAULT 0
    )''')
    
    conn.commit()
    conn.close()
    print("✅ База даних ініціалізована")

def log_event(gate_id, event_type, source, duration=None):
    """Логування події"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO gate_events (gate_id, event_type, source, duration)
                 VALUES (?, ?, ?, ?)''', (gate_id, event_type, source, duration))
    conn.commit()
    conn.close()
    update_daily_stats()

def log_alert(gate_id, start_time, end_time=None, resolved_by=None):
    """Логування аварії"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if end_time:
        duration = int((datetime.now() - datetime.fromisoformat(start_time)).total_seconds())
        c.execute('''UPDATE alerts 
                     SET end_time = ?, duration = ?, resolved_by = ?, resolved_at = ?
                     WHERE gate_id = ? AND start_time = ?''',
                  (end_time, duration, resolved_by, datetime.now(), gate_id, start_time))
    else:
        c.execute('''INSERT INTO alerts (gate_id, start_time)
                     VALUES (?, ?)''', (gate_id, start_time))
    conn.commit()
    conn.close()
    update_daily_stats()

def update_daily_stats():
    """Оновлення щоденної статистики"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date()
    
    c.execute('''SELECT 
        COUNT(CASE WHEN event_type = 'open' THEN 1 END) as opens,
        COUNT(CASE WHEN event_type = 'alert' THEN 1 END) as alerts,
        COALESCE(SUM(duration), 0) as total_duration
        FROM gate_events 
        WHERE DATE(timestamp) = ?''', (today,))
    
    result = c.fetchone()
    opens, alerts, total_duration = result
    
    avg_duration = total_duration // opens if opens > 0 else 0
    
    c.execute('''INSERT OR REPLACE INTO daily_stats (date, total_opens, total_alerts, total_duration, avg_duration)
                 VALUES (?, ?, ?, ?, ?)''', (today, opens, alerts, total_duration, avg_duration))
    
    conn.commit()
    conn.close()

def get_stats(days=7):
    """Отримання статистики за останні N днів"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    date_limit = datetime.now() - timedelta(days=days)
    c.execute('''SELECT date, total_opens, total_alerts, total_duration, avg_duration
                 FROM daily_stats 
                 WHERE date >= ?
                 ORDER BY date DESC''', (date_limit.date(),))
    
    stats = [{'date': row[0], 'opens': row[1], 'alerts': row[2], 
              'total_duration': row[3], 'avg_duration': row[4]} 
             for row in c.fetchall()]
    conn.close()
    return stats

def get_current_status():
    """Отримання поточного статусу всіх воріт"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''SELECT gate_id, event_type, timestamp, duration
                 FROM gate_events 
                 WHERE (gate_id, timestamp) IN (
                     SELECT gate_id, MAX(timestamp) 
                     FROM gate_events 
                     GROUP BY gate_id
                 )''')
    
    status = {}
    for row in c.fetchall():
        gate_id = row[0]
        event_type = row[1]
        timestamp = row[2]
        if event_type == 'open':
            duration = int((datetime.now() - datetime.fromisoformat(timestamp)).total_seconds())
            status[gate_id] = {
                'status': 'open',
                'since': timestamp,
                'duration': duration
            }
        else:
            status[gate_id] = {'status': 'closed'}
    
    conn.close()
    return status

def get_alerts_today():
    """Отримання аварій за сьогодні"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date()
    
    c.execute('''SELECT gate_id, start_time, end_time, duration, resolved_by
                 FROM alerts 
                 WHERE DATE(start_time) = ?
                 ORDER BY start_time DESC''', (today,))
    
    alerts = [{'gate_id': row[0], 'start': row[1], 'end': row[2], 
               'duration': row[3], 'resolved_by': row[4]} 
              for row in c.fetchall()]
    conn.close()
    return alerts

def send_telegram_alert(message):
    """Надсилання сповіщення в Telegram"""
    try:
        bot.send_message(CHAT_ID, message, parse_mode="Markdown")
    except Exception as e:
        print(f"Помилка сповіщення: {e}")

# ===== БАЗА ДАНИХ ВОРІТ ДЛЯ ЕМУЛЯЦІЇ =====
gates = {}
for i in range(1, TOTAL_GATES + 1):
    gates[i] = {
        "status": "closed",
        "open_since": 0,
        "alert_sent": False
    }

lock = threading.Lock()

# ===== ДОПОМІЖНІ ФУНКЦІЇ =====
def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes} хв {secs} сек"

# ===== ФОНОВИЙ МОНІТОРИНГ =====
def monitor_logic():
    print("🔄 Фоновий моніторинг запущено")
    while True:
        with lock:
            now = time.time()
            for gate_id, state in gates.items():
                if state["status"] == "open":
                    elapsed = now - state["open_since"]
                    if elapsed >= MAX_OPEN_TIME_SEC and not state["alert_sent"]:
                        alert_msg = f"🚨 *АВАРІЯ!* \nВорота *№{gate_id}* відкриті понад {MAX_OPEN_TIME_SEC} сек! \n🛑 Тривалість: {format_time(elapsed)}"
                        send_telegram_alert(alert_msg)
                        state["alert_sent"] = True
                        log_event(gate_id, 'alert', 'system', int(elapsed))
                        log_alert(gate_id, datetime.now().isoformat())
                        print(f"⚠️ Аварія на воротах №{gate_id}")
        time.sleep(1)

# ===== АВТОМАТИЧНИЙ ПІНГ (щоб бот не засинав) =====
def keep_alive():
    """Пінг кожні 4 хвилини щоб бот не засинав"""
    while True:
        try:
            requests.get('https://gate-bot-io6g.onrender.com/health', timeout=5)
            print("💓 Пінг відправлено")
        except Exception as e:
            print(f"❌ Помилка пінгу: {e}")
        time.sleep(240)  # 4 хвилини

# ===== API ДЛЯ ESP32 =====
@app.route('/api/gate/status', methods=['POST'])
def gate_status():
    """API для ESP32: отримання статусу воріт"""
    try:
        data = request.get_json()
        gate_id = data.get('gate_id')
        status = data.get('status')
        
        if not gate_id or not status:
            return jsonify({"error": "Missing gate_id or status"}), 400
        
        if status == 'open':
            log_event(gate_id, 'open', 'esp32')
            send_telegram_alert(f"🔓 *Ворота №{gate_id}* відкриті (ESP32)")
            
            # Оновлення внутрішнього стану
            with lock:
                if gate_id <= TOTAL_GATES:
                    gates[gate_id]["status"] = "open"
                    gates[gate_id]["open_since"] = time.time()
                    gates[gate_id]["alert_sent"] = False
            
            return jsonify({"status": "ok", "message": f"Gate {gate_id} opened"}), 200
        
        elif status == 'close':
            # Розрахунок тривалості
            duration = 0
            with lock:
                if gate_id <= TOTAL_GATES and gates[gate_id]["status"] == "open":
                    duration = int(time.time() - gates[gate_id]["open_since"])
                    gates[gate_id]["status"] = "closed"
            
            log_event(gate_id, 'close', 'esp32', duration)
            return jsonify({"status": "ok", "message": f"Gate {gate_id} closed"}), 200
        
        else:
            return jsonify({"error": "Invalid status"}), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/gate/alert', methods=['POST'])
def gate_alert():
    """API для ESP32: сповіщення про аварію"""
    try:
        data = request.get_json()
        gate_id = data.get('gate_id')
        reason = data.get('reason', 'unknown')
        
        log_event(gate_id, 'alert', 'esp32')
        log_alert(gate_id, datetime.now().isoformat())
        
        send_telegram_alert(f"🚨 *КРИТИЧНА АВАРІЯ!*\nВорота №{gate_id}\nПричина: {reason}\n⚠️ ПОТРІБНЕ ВТРУЧАННЯ!")
        
        return jsonify({"status": "ok", "message": "Alert sent"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/status/all', methods=['GET'])
def get_all_status():
    """Отримання статусу всіх воріт (для ESP32)"""
    status = get_current_status()
    return jsonify(status), 200

@app.route('/api/test', methods=['GET'])
def test_api():
    """Тестовий ендпоінт"""
    return jsonify({
        "status": "ok",
        "message": "API для ESP32 працює",
        "endpoints": [
            "POST /api/gate/status - оновити статус",
            "POST /api/gate/alert - сповіщення про аварію",
            "GET /api/status/all - отримати всі статуси"
        ]
    }), 200

# ===== ОБРОБНИКИ TELEGRAM =====
@bot.message_handler(commands=['start'])
def start_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_emu = types.KeyboardButton("🎲 Емулювати випадкові ворота")
    btn_status = types.KeyboardButton("📊 Статус усіх воріт")
    btn_stats = types.KeyboardButton("📈 Статистика")
    btn_alerts = types.KeyboardButton("🚨 Аварії сьогодні")
    markup.add(btn_emu, btn_status)
    markup.add(btn_stats, btn_alerts)
    
    bot.send_message(
        message.chat.id, 
        f"🚀 *Система моніторингу {TOTAL_GATES} воріт запущена!*\n\n"
        f"📌 *Команди:*\n"
        f"🎲 Емулювати випадкові ворота - відкрити випадкові ворота\n"
        f"📊 Статус усіх воріт - перевірити які ворота відкриті\n"
        f"📈 Статистика - статистика за останні 7 днів\n"
        f"🚨 Аварії сьогодні - список аварій за сьогодні\n\n"
        f"⚠️ Якщо ворота будуть відкриті більше {MAX_OPEN_TIME_SEC} секунд - надійде сповіщення!",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.message_handler(commands=['stats'])
def show_stats_command(message):
    show_stats(message)

@bot.message_handler(commands=['alerts'])
def show_alerts_command(message):
    show_alerts(message)

@bot.message_handler(commands=['status_all'])
def status_all_command(message):
    status_all(message)

@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    if message.text == "🎲 Емулювати випадкові ворота":
        gate_num = random.randint(1, TOTAL_GATES)
        with lock:
            if gates[gate_num]["status"] == "closed":
                gates[gate_num]["status"] = "open"
                gates[gate_num]["open_since"] = time.time()
                gates[gate_num]["alert_sent"] = False
                
                log_event(gate_num, 'open', 'bot_emulation')
                
                inline_markup = types.InlineKeyboardMarkup()
                btn_close = types.InlineKeyboardButton(
                    f"✅ Закрити ворота №{gate_num}", 
                    callback_data=f"close_{gate_num}"
                )
                inline_markup.add(btn_close)
                
                bot.send_message(
                    CHAT_ID, 
                    f"🔼 *Ворота №{gate_num}* відкрито (емуляція).\n⏱ Лічильник запущено!",
                    parse_mode="Markdown", 
                    reply_markup=inline_markup
                )
                print(f"🚪 Відкрито ворота №{gate_num}")
            else:
                bot.send_message(
                    CHAT_ID, 
                    f"ℹ️ Ворота №{gate_num} вже відкриті."
                )
    
    elif message.text == "📊 Статус усіх воріт":
        with lock:
            open_gates = [str(id) for id, st in gates.items() if st["status"] == "open"]
            if open_gates:
                response = f"📂 *Відкриті ворота:* {', '.join(open_gates)}\n\n📊 *Всього відкрито:* {len(open_gates)} з {TOTAL_GATES}"
            else:
                response = "✅ *Всі ворота закриті!* \nСистема працює в штатному режимі."
        bot.send_message(CHAT_ID, response, parse_mode="Markdown")
    
    elif message.text == "📈 Статистика":
        show_stats(message)
    
    elif message.text == "🚨 Аварії сьогодні":
        show_alerts(message)

def show_stats(message):
    """Статистика за останні 7 днів"""
    stats = get_stats(7)
    
    if not stats:
        bot.reply_to(message, "📊 Статистика ще не накопичена")
        return
    
    response = "📊 *Статистика за останні 7 днів:*\n\n"
    for stat in stats:
        response += f"📅 {stat['date']}: {stat['opens']} відкриттів, {stat['alerts']} аварій\n"
        response += f"   ⏱ Середній час: {stat['avg_duration']} сек\n\n"
    
    bot.reply_to(message, response, parse_mode="Markdown")

def show_alerts(message):
    """Аварії за сьогодні"""
    alerts = get_alerts_today()
    
    if not alerts:
        bot.reply_to(message, "✅ За сьогодні аварій немає")
        return
    
    response = "🚨 *Аварії за сьогодні:*\n\n"
    for alert in alerts:
        response += f"🚪 Ворота №{alert['gate_id']}\n"
        response += f"⏱ Початок: {alert['start'][:19]}\n"
        if alert['end']:
            response += f"✅ Вирішено: {alert['resolved_by']}\n"
            response += f"⏱ Тривалість: {alert['duration']} сек\n"
        else:
            response += "⚠️ *АКТИВНА АВАРІЯ!*\n"
        response += "\n"
    
    bot.reply_to(message, response, parse_mode="Markdown")

def status_all(message):
    """Статус всіх воріт з часом"""
    with lock:
        open_gates = []
        for gate_id, state in gates.items():
            if state["status"] == "open":
                duration = int(time.time() - state["open_since"])
                open_gates.append(f"🚪 Ворота №{gate_id}: відкриті {duration} сек")
    
    if open_gates:
        response = "📂 *Поточний статус:*\n\n" + "\n".join(open_gates)
    else:
        response = "✅ *Всі ворота закриті!*"
    
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('close_'))
def callback_close_gate(call):
    gate_num = int(call.data.split('_')[1])
    with lock:
        if gates[gate_num]["status"] == "open":
            duration = int(time.time() - gates[gate_num]["open_since"])
            gates[gate_num]["status"] = "closed"
            
            log_event(gate_num, 'close', 'bot', duration)
            
            bot.edit_message_text(
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id, 
                text=f"✅ *Ворота №{gate_num}* закриті.\n⏱ Були відкриті: {format_time(duration)}", 
                parse_mode="Markdown"
            )
            
            if gates[gate_num]["alert_sent"]:
                send_telegram_alert(
                    f"🟢 *ПРОБЛЕМУ УСУНЕНО:* Ворота №{gate_num} нарешті закриті.\n⏱ Час аварії: {format_time(duration)}"
                )
                log_alert(gate_num, datetime.now().isoformat(), datetime.now().isoformat(), 'bot')
            
            gates[gate_num]["alert_sent"] = False
            print(f"🔒 Закрито ворота №{gate_num} (були відкриті {format_time(duration)})")

# ===== FLASK МАРШРУТИ =====
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        print(f"❌ Помилка webhook: {e}")
        return 'OK', 200

@app.route('/')
def index():
    return f"🚀 Бот моніторингу {TOTAL_GATES} воріт працює!", 200

@app.route('/health')
def health():
    with lock:
        open_count = sum(1 for g in gates.values() if g["status"] == "open")
    return {
        "status": "ok",
        "total_gates": TOTAL_GATES,
        "open_gates": open_count,
        "max_open_time": MAX_OPEN_TIME_SEC,
        "timestamp": time.time()
    }, 200

# ===== ЗАПУСК ФОНОВИХ ПОТОКІВ =====
# Ініціалізація бази даних
init_db()

# Запуск моніторингу
monitor_thread = threading.Thread(target=monitor_logic, daemon=True)
monitor_thread.start()

# Запуск автопінгу (щоб бот не засинав)
ping_thread = threading.Thread(target=keep_alive, daemon=True)
ping_thread.start()

# ===== ОСНОВНИЙ ЗАПУСК =====
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 Бот моніторингу воріт запущено!")
    print(f"📊 Всього воріт: {TOTAL_GATES}")
    print(f"⏱ Час аварії: {MAX_OPEN_TIME_SEC} сек")
    print(f"🔗 Webhook URL: /webhook")
    print(f"📡 API для ESP32: /api/...")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8080)

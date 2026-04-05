import telebot
import time
import threading
import random
from telebot import types
from flask import Flask, request
import os

# ===== КОНФІГУРАЦІЯ =====
BOT_TOKEN = "8670900193:AAF3c82nGP-6b5F25NM_RHYekoVqMQ2un7c"
CHAT_ID = "209403052"
MAX_OPEN_TIME_SEC = 60
TOTAL_GATES = 50

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ===== БАЗА ДАНИХ ВОРІТ =====
gates = {}
for i in range(1, TOTAL_GATES + 1):
    gates[i] = {
        "status": "closed",
        "open_since": 0,
        "alert_sent": False
    }

lock = threading.Lock()

# ===== ДОПОМІЖНІ ФУНКЦІЇ =====
def send_telegram(message):
    try:
        bot.send_message(CHAT_ID, message, parse_mode="Markdown")
    except Exception as e:
        print(f"Помилка надсилання: {e}")

def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes} хв {secs} сек"

# ===== ФОНОВИЙ МОНІТОРИНГ (60 СЕКУНД) =====
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
                        send_telegram(alert_msg)
                        state["alert_sent"] = True
                        print(f"⚠️ Аварія на воротах №{gate_id}")
        time.sleep(1)

# ===== ОБРОБНИКИ TELEGRAM =====
@bot.message_handler(commands=['start'])
def start_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_emu = types.KeyboardButton("🎲 Емулювати випадкові ворота")
    btn_status = types.KeyboardButton("📊 Статус усіх воріт")
    markup.add(btn_emu, btn_status)
    bot.send_message(
        message.chat.id, 
        "🚀 Система моніторингу 50 воріт запущена.\n\n"
        "📌 *Команди:*\n"
        "🎲 Емулювати випадкові ворота - відкрити випадкові ворота\n"
        "📊 Статус усіх воріт - перевірити які ворота відкриті\n\n"
        "⚠️ Якщо ворота будуть відкриті більше 60 секунд - надійде сповіщення!",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    if message.text == "🎲 Емулювати випадкові ворота":
        gate_num = random.randint(1, TOTAL_GATES)
        with lock:
            if gates[gate_num]["status"] == "closed":
                gates[gate_num]["status"] = "open"
                gates[gate_num]["open_since"] = time.time()
                gates[gate_num]["alert_sent"] = False
                
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
        open_gates = [str(id) for id, st in gates.items() if st["status"] == "open"]
        if open_gates:
            bot.send_message(
                CHAT_ID, 
                f"📂 *Відкриті ворота:* {', '.join(open_gates)}\n\n📊 *Всього відкрито:* {len(open_gates)} з {TOTAL_GATES}",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                CHAT_ID, 
                "✅ *Всі ворота закриті!* \nСистема працює в штатному режимі.",
                parse_mode="Markdown"
            )

@bot.callback_query_handler(func=lambda call: call.data.startswith('close_'))
def callback_close_gate(call):
    gate_num = int(call.data.split('_')[1])
    with lock:
        if gates[gate_num]["status"] == "open":
            duration = time.time() - gates[gate_num]["open_since"]
            gates[gate_num]["status"] = "closed"
            
            bot.edit_message_text(
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id, 
                text=f"✅ *Ворота №{gate_num}* закриті.\n⏱ Були відкриті: {format_time(duration)}", 
                parse_mode="Markdown"
            )
            
            if gates[gate_num]["alert_sent"]:
                send_telegram(
                    f"🟢 *ПРОБЛЕМУ УСУНЕНО:* Ворота №{gate_num} нарешті закриті.\n⏱ Час аварії: {format_time(duration)}"
                )
            
            gates[gate_num]["alert_sent"] = False
            print(f"🔒 Закрито ворота №{gate_num} (були відкриті {format_time(duration)})")

# ===== FLASK МАРШРУТИ ДЛЯ WEBHOOK =====
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
    return "🚀 Бот моніторингу воріт працює!", 200

@app.route('/health')
def health():
    open_count = sum(1 for g in gates.values() if g["status"] == "open")
    return {
        "status": "ok",
        "total_gates": TOTAL_GATES,
        "open_gates": open_count,
        "timestamp": time.time()
    }, 200

# ===== ЗАПУСК ФОНОВОГО ПОТОКУ =====
monitor_thread = threading.Thread(target=monitor_logic, daemon=True)
monitor_thread.start()

# ===== ОСНОВНИЙ ЗАПУСК =====
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 Бот моніторингу воріт запущено!")
    print(f"📊 Всього воріт: {TOTAL_GATES}")
    print(f"⏱ Час аварії: {MAX_OPEN_TIME_SEC} сек")
    print(f"🔗 Webhook URL: /webhook")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8080)

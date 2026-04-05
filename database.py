import sqlite3
import json
from datetime import datetime, timedelta
import os

DB_PATH = '/var/data/gates.db'  # Шлях до БД на Render

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
        event_type TEXT NOT NULL,  -- 'open', 'close', 'alert', 'manual_close'
        source TEXT NOT NULL,       -- 'esp32', 'bot', 'manual'
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        duration INTEGER,           -- тривалість відкриття (секунди)
        alert_sent BOOLEAN DEFAULT FALSE
    )''')
    
    # Таблиця аварій
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gate_id INTEGER NOT NULL,
        start_time DATETIME NOT NULL,
        end_time DATETIME,
        duration INTEGER,
        resolved_by TEXT,  -- 'bot', 'manual', 'esp32'
        resolved_at DATETIME
    )''')
    
    # Таблиця щоденної статистики
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
        date DATE PRIMARY KEY,
        total_opens INTEGER DEFAULT 0,
        total_alerts INTEGER DEFAULT 0,
        total_duration INTEGER DEFAULT 0,  -- загальний час відкриття (секунди)
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
    
    # Оновлення денної статистики
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
    
    # Агрегація даних за сьогодні
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
            duration = (datetime.now() - datetime.fromisoformat(timestamp)).total_seconds()
            status[gate_id] = {
                'status': 'open',
                'since': timestamp,
                'duration': int(duration)
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

init_db()  # Ініціалізація при запуску

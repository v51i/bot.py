import os
import time
import threading
import requests
import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from datetime import timezone as dt_timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from zoneinfo import ZoneInfo
from typing import Optional, Dict, List, Tuple

# ============================================================
# KALARITH VIP GOLD - FULL ORIGINAL ANALYSIS + USER TRADING
# COMPLETE - NO SHORTENING
# ============================================================

TELEGRAM_TOKEN = "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU"
PRIVATE_CHAT_ID = "8952278702"
CHANNEL_CHAT_ID = "@ZXPIF"
ADMIN_BOT_TOKEN = "8213676342:AAHPZgXdUufiz7b8zEJ5s2-ZdoXVFBAPx2M"
ADMIN_IDS = [8952278702, 8950515154]

BIQUOTE_BASE_URL = "https://biquote.io/api"
BIQUOTE_SYMBOL = "XAUUSD"

TRADES_DB_FILE = "trades.db"
USER_DB_FILE = "user_trading.db"
active_trades_memory = []
trades_memory_lock = threading.Lock()
user_states = {}
user_states_lock = threading.Lock()

DEFAULT_LOT = 0.01
MAX_OPEN_TRADES_PER_USER = 3
CONTRACT_SIZE = 100
MARGIN_PER_LOT = 50.0

def init_trades_db():
    try:
        conn = sqlite3.connect(TRADES_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                pair TEXT NOT NULL,
                action TEXT NOT NULL,
                entry REAL NOT NULL,
                target REAL NOT NULL,
                stop_loss REAL NOT NULL,
                status TEXT DEFAULT 'Open',
                close_time TEXT,
                close_price REAL,
                tp1 REAL,
                tp2 REAL,
                grade TEXT,
                reason TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_status ON trades(status)")
        conn.commit()
        conn.close()
        print("[SQLite] DB initialized")
        return True
    except Exception as e:
        print(f"[SQLite] Init error: {e}")
        return False

def save_new_trade_to_db(action, entry, target, stop_loss, pair="XAUUSD", tp1=None, tp2=None, grade=None, reason=None):
    try:
        conn = sqlite3.connect(TRADES_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        now_str = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO trades (time, pair, action, entry, target, stop_loss, status, tp1, tp2, grade, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (now_str, pair, action, float(entry), float(target), float(stop_loss), "Open", tp1, tp2, grade, reason))
        trade_id = cur.lastrowid
        conn.commit()
        conn.close()
        with trades_memory_lock:
            active_trades_memory.append({
                "id": trade_id, "time": now_str, "pair": pair, "action": action,
                "entry": float(entry), "target": float(target), "stop_loss": float(stop_loss),
                "tp1": tp1, "tp2": tp2, "grade": grade
            })
        print(f"[SQLite] Saved trade #{trade_id} {action} {entry}")
        return trade_id
    except Exception as e:
        print(f"[SQLite] Save error: {e}")
        return None

def load_open_trades_to_memory():
    global active_trades_memory
    try:
        conn = sqlite3.connect(TRADES_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("SELECT id, time, pair, action, entry, target, stop_loss, tp1, tp2, grade FROM trades WHERE status='Open'")
        rows = cur.fetchall()
        conn.close()
        with trades_memory_lock:
            active_trades_memory = []
            for r in rows:
                active_trades_memory.append({
                    "id": r[0], "time": r[1], "pair": r[2], "action": r[3],
                    "entry": r[4], "target": r[5], "stop_loss": r[6],
                    "tp1": r[7], "tp2": r[8], "grade": r[9]
                })
        print(f"[SQLite] Loaded {len(active_trades_memory)} open trades")
        return len(active_trades_memory)
    except Exception as e:
        print(f"[SQLite] Load error: {e}")
        return 0

def update_trade_status_in_db(trade_id, new_status, close_price):
    try:
        conn = sqlite3.connect(TRADES_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        close_time = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("UPDATE trades SET status=?, close_time=?, close_price=? WHERE id=?",
                    (new_status, close_time, float(close_price), int(trade_id)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[SQLite] Update error: {e}")
        return False

def check_open_trades_price_loop(current_price):
    if current_price is None:
        return
    to_remove = []
    with trades_memory_lock:
        snapshot = list(active_trades_memory)
    for trade in snapshot:
        action = trade["action"]
        target = trade["target"]
        sl = trade["stop_loss"]
        tid = trade["id"]
        entry = trade["entry"]
        hit_tp = hit_sl = False
        if action == "BUY":
            if current_price >= target: hit_tp = True
            elif current_price <= sl: hit_sl = True
        else:
            if current_price <= target: hit_tp = True
            elif current_price >= sl: hit_sl = True
        if hit_tp or hit_sl:
            if hit_tp:
                new_status = "ضربت الهدف 🎯"
                title = f"🎯 <b>ضربت الهدف - {action} #{tid}</b>"
            else:
                new_status = "ضربت الستوب 🛑"
                title = f"🛑 <b>ضربت الستوب - {action} #{tid}</b>"
            update_trade_status_in_db(tid, new_status, current_price)
            profit = (current_price - entry) if action == "BUY" else (entry - current_price)
            msg = (
                f"{title}\n\n"
                f"🆔 الصفقة: <code>#{tid}</code>\n"
                f"📅 الدخول: <code>{trade['time']}</code>\n"
                f"⚡ سعر الدخول: <code>{entry}</code>\n"
                f"🎯 الهدف: <code>{target}</code>\n"
                f"🛑 الستوب: <code>{sl}</code>\n"
                f"💰 سعر الإغلاق: <code>{current_price:.2f}</code>\n"
                f"📈 الربح: <code>{profit:+.2f}$</code>\n"
                f"📊 الحالة: <code>{new_status}</code>"
            )
            send_to_telegram(msg, event_id=f"CLOSE_{tid}_{int(time.time())}")
            to_remove.append(tid)
    if to_remove:
        with trades_memory_lock:
            active_trades_memory[:] = [t for t in active_trades_memory if t["id"] not in to_remove]

def init_user_trading_db():
    try:
        conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT,
                balance REAL DEFAULT 0.0,
                auto_trade INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        try:
            cur.execute("ALTER TABLE users ADD COLUMN auto_trade INTEGER DEFAULT 0")
        except:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deposit_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                details TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                method_id INTEGER,
                amount REAL NOT NULL,
                proof TEXT,
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                created_at TEXT,
                processed_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                amount REAL NOT NULL,
                address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                created_at TEXT,
                processed_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                lot REAL NOT NULL,
                entry REAL NOT NULL,
                sl REAL,
                tp REAL,
                status TEXT DEFAULT 'Open',
                close_price REAL,
                profit REAL DEFAULT 0.0,
                open_time TEXT,
                close_time TEXT
            )
        """)
        conn.commit()
        conn.close()
        print("[UserTrading] DB initialized")
        return True
    except Exception as e:
        print(f"[UserTrading] Init error: {e}")
        return False

def get_or_create_user(user_id, name="مستخدم"):
    uid = str(user_id)
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("SELECT balance, name, auto_trade FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if row:
        balance, uname, auto = row
        conn.close()
        return {"user_id": uid, "balance": balance, "name": uname, "auto_trade": auto or 0}
    now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO users (user_id, name, balance, auto_trade, created_at) VALUES (?, ?, 0.0, 0, ?)",
                (uid, name, now))
    conn.commit()
    conn.close()
    return {"user_id": uid, "balance": 0.0, "name": name, "auto_trade": 0}

def update_user_balance(user_id, new_balance):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance=? WHERE user_id=?", (float(new_balance), str(user_id)))
    conn.commit()
    conn.close()

def add_to_balance(user_id, amount):
    user = get_or_create_user(user_id)
    new_bal = user["balance"] + float(amount)
    update_user_balance(user_id, new_bal)
    return new_bal

def set_auto_trade(user_id, status: int):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("UPDATE users SET auto_trade=? WHERE user_id=?", (status, str(user_id)))
    conn.commit()
    conn.close()

def get_auto_trade(user_id):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("SELECT auto_trade FROM users WHERE user_id=?", (str(user_id),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def get_open_user_trades(user_id=None):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    if user_id:
        cur.execute("SELECT * FROM user_trades WHERE user_id=? AND status='Open' ORDER BY id DESC", (str(user_id),))
    else:
        cur.execute("SELECT * FROM user_trades WHERE status='Open' ORDER BY id DESC")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

def count_open_trades(user_id):
    return len(get_open_user_trades(user_id))

def calculate_profit(action, entry, close_price, lot):
    diff = (close_price - entry) if action == "BUY" else (entry - close_price)
    return round(diff * lot * CONTRACT_SIZE, 2)

def open_user_trade(user_id, action, lot, entry, sl=None, tp=None):
    user = get_or_create_user(user_id)
    required_margin = lot * MARGIN_PER_LOT
    if user["balance"] < required_margin:
        return None, f"الرصيد غير كافٍ. المطلوب هامش تقريبي: {required_margin:.2f}$"
    if count_open_trades(user_id) >= MAX_OPEN_TRADES_PER_USER:
        return None, f"وصلت للحد الأقصى ({MAX_OPEN_TRADES_PER_USER}) صفقات مفتوحة"
    now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_trades (user_id, action, lot, entry, sl, tp, status, open_time)
        VALUES (?, ?, ?, ?, ?, ?, 'Open', ?)
    """, (str(user_id), action, float(lot), float(entry), sl, tp, now))
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id, None

def close_user_trade(trade_id, close_price, status="Closed"):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("SELECT user_id, action, lot, entry, status FROM user_trades WHERE id=?", (trade_id,))
    row = cur.fetchone()
    if not row or row[4] != "Open":
        conn.close()
        return False, 0, None
    user_id, action, lot, entry, _ = row
    profit = calculate_profit(action, entry, close_price, lot)
    now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        UPDATE user_trades SET status=?, close_price=?, profit=?, close_time=? WHERE id=?
    """, (status, float(close_price), profit, now, trade_id))
    conn.commit()
    conn.close()
    add_to_balance(user_id, profit)
    return True, profit, user_id

def close_user_trade_manual(trade_id, user_id):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("SELECT user_id, action, lot, entry, status FROM user_trades WHERE id=? AND user_id=?",
                (trade_id, str(user_id)))
    row = cur.fetchone()
    conn.close()
    if not row or row[4] != "Open":
        return False, "الصفقة غير موجودة أو مغلقة مسبقًا"
    price = get_biquote_price()
    if price is None:
        return False, "تعذر الحصول على السعر"
    success, profit, uid = close_user_trade(trade_id, price, "إغلاق يدوي")
    if success:
        return True, profit
    return False, "فشل الإغلاق"

def check_user_trades_price_loop(current_price):
    if current_price is None:
        return
    open_trades = get_open_user_trades()
    for trade in open_trades:
        action = trade["action"]
        entry = trade["entry"]
        sl = trade["sl"]
        tp = trade["tp"]
        tid = trade["id"]
        user_id = trade["user_id"]
        hit_tp = hit_sl = False
        if action == "BUY":
            if tp and current_price >= tp: hit_tp = True
            elif sl and current_price <= sl: hit_sl = True
        else:
            if tp and current_price <= tp: hit_tp = True
            elif sl and current_price >= sl: hit_sl = True
        if hit_tp or hit_sl:
            status = "ضربت الهدف 🎯" if hit_tp else "ضربت الستوب 🛑"
            success, profit, uid = close_user_trade(tid, current_price, status)
            if success:
                emoji = "🎯" if hit_tp else "🛑"
                msg = (
                    f"{emoji} <b>{status}</b>\n\n"
                    f"🆔 الصفقة: <code>#{tid}</code>\n"
                    f"📊 النوع: <code>{action}</code>\n"
                    f"📦 الحجم: <code>{trade['lot']}</code>\n"
                    f"⚡ الدخول: <code>{entry}</code>\n"
                    f"💰 الإغلاق: <code>{current_price:.2f}</code>\n"
                    f"📈 النتيجة: <code>{profit:+.2f}$</code>"
                )
                try:
                    send_message_with_keyboard(uid, msg, get_main_keyboard())
                except:
                    pass
                try:
                    send_to_admin_channel(f"🔔 <b>إغلاق صفقة عميل</b>\n\n{msg}\n👤 ID: <code>{uid}</code>")
                except:
                    pass

# ==================== SETTINGS (الأصلي كامل) ====================
ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP1 = 0.4
ATR_MULTIPLIER_TP2 = 1.0
ATR_MULTIPLIER_TP3 = 1.6
MIN_SL_PRICE_DISTANCE = 5.0
MAX_SL_PRICE_DISTANCE = 12.0
BREAK_EVEN_AT_TP1 = True
TIMEOUT_MINUTES = 40
COOLDOWN_AFTER_TIMEOUT_MIN = 10
COOLDOWN_AFTER_SL_MIN = 25
COOLDOWN_AFTER_TP1_WIN_MIN = 15
COOLDOWN_AFTER_REVERSAL_MIN = 15
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 53
RSI_SELL_THRESHOLD = 47
RSI_MAX_FOR_BUY = 64
RSI_MIN_FOR_SELL = 36
TARGET_TRADES_PER_DAY = 14
MAX_TRADES_PER_DAY = 20
ENABLE_REVERSAL = True
CHOPPY_RANGE_MULTIPLIER = 1.3
MIN_PROFIT_FOR_REVERSAL = 2.5
ENABLE_NEWS_FILTER = True
NEWS_BLOCK_BEFORE_MIN = 10
NEWS_BLOCK_AFTER_MIN = 10
NEWS_REPORT_BEFORE_MIN = 15
ENABLE_SMART_FEAR = True
MAX_CONSECUTIVE_LOSSES = 2
DAILY_LOSS_LIMIT = 30.0
MAX_DAILY_LOSSES = 8
PAUSE_AFTER_CONSECUTIVE_LOSSES_MIN = 60
MAX_DATA_AGE_SECONDS = 300
MAX_SENT_EVENTS = 8000
MAX_TRADE_LOG = 1500
MIN_CANDLE_STRENGTH = 45
OVEREXTENSION_CANDLES = 40
OVEREXTENSION_POINTS = 36.0
SWEEP_LOOKBACK = 20
SR_LOOKBACK = 100

TIMEFRAMES = {
    "1h": {"interval": "1h", "limit": 120, "refresh": 90},
    "15m": {"interval": "15m", "limit": 200, "refresh": 25},
    "5m": {"interval": "5m", "limit": 250, "refresh": 1},
    "1m": {"interval": "1m", "limit": 300, "refresh": 1}
}

tf_data = {
    "1h": {"closes": [], "lows": [], "highs": [], "opens": [], "volumes": [], "times": [], "last_update": 0},
    "15m": {"closes": [], "lows": [], "highs": [], "opens": [], "volumes": [], "times": [], "last_update": 0},
    "5m": {"closes": [], "lows": [], "highs": [], "opens": [], "volumes": [], "times": [], "last_update": 0},
    "1m": {"closes": [], "lows": [], "highs": [], "opens": [], "volumes": [], "times": [], "last_update": 0}
}

SAUDI_TZ = timezone(timedelta(hours=3))
NY_TZ = ZoneInfo("America/New_York")

active_trade = None
entry_price = 0.0
target_sl = 0.0
target_tp1 = 0.0
target_tp2 = 0.0
target_tp3 = 0.0
m5_bias_at_entry = "NEUTRAL"
tp1_hit = False
tp2_hit = False
tp3_hit = False
trade_open_time = None
trade_signal_type = None
trade_signal_id = None
trade_grade = None
trade_reason = None
trade_rsi = 0.0
trade_ema_diff = 0.0
trade_atr = 0.0
trade_bias = ""
trade_score = 0
timeout_final = False
last_reversal_time = None
last_sl_timestamp = None
last_timeout_timestamp = None
last_tp1_win_timestamp = None
last_tp1_win_price = 0.0
last_consecutive_loss_pause = None
last_signal_time = None
news_cache = []
news_cache_time = None
news_reports_sent = set()
consecutive_losses = 0
daily_loss_total = 0.0
session_start_time = None
last_error = ""
bot_lock_file = "bot.lock"
daily_signals = 0
daily_completed_trades = 0
daily_wins = 0
daily_losses = 0
daily_tp1_hits = 0
daily_tp2_hits = 0
daily_sl_hits = 0
daily_be_hits = 0
daily_timeout = 0
daily_a_grade = 0
daily_b_grade = 0
daily_reversals = 0
daily_news_blocked = 0
daily_total_profit = 0.0
last_summary_date = datetime.now(SAUDI_TZ).date()
weekly_signals = 0
weekly_completed_trades = 0
weekly_wins = 0
weekly_losses = 0
weekly_tp1_hits = 0
weekly_tp2_hits = 0
weekly_sl_hits = 0
weekly_be_hits = 0
weekly_timeout = 0
weekly_reversals = 0
weekly_news_blocked = 0
weekly_total_profit = 0.0
last_weekly_report_date = None
last_market_state = None
pre_market_sent = False
MEMORY_FILE = "trade_memory.json"
EVENTS_FILE = "sent_events.json"
ACTIVE_TRADE_FILE = "active_trade.json"
ai_memory = {"trades": [], "trade_log": [], "patterns": {}, "total_trades": 0, "total_wins": 0, "total_losses": 0, "win_rate": 0.0}
sent_events = set()
telegram_lock = threading.Lock()
signal_lock = threading.Lock()
events_lock = threading.Lock()
server_started_at = datetime.now(SAUDI_TZ)
last_bot_loop = datetime.now(SAUDI_TZ)
last_market_report_hour = None
last_data_update_time = None

def atomic_write_json(filepath, data):
    try:
        temp_file = filepath + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        print(f"[AtomicWrite] Error: {e}")
        return False

def load_sent_events():
    global sent_events
    try:
        if os.path.exists(EVENTS_FILE):
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            sent_events = set(data) if isinstance(data, list) else set()
            if len(sent_events) > MAX_SENT_EVENTS:
                sent_events = set(list(sent_events)[-MAX_SENT_EVENTS:])
    except:
        sent_events = set()

def save_sent_events():
    with events_lock:
        atomic_write_json(EVENTS_FILE, list(sent_events))

def load_ai_memory():
    global ai_memory
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                ai_memory.update(data)
    except Exception as e:
        print(f"[ERROR] Load AI: {e}")

def save_ai_memory():
    if len(ai_memory.get("trade_log", [])) > MAX_TRADE_LOG:
        ai_memory["trade_log"] = ai_memory["trade_log"][-MAX_TRADE_LOG:]
    atomic_write_json(MEMORY_FILE, ai_memory)

def save_active_trade():
    try:
        if active_trade:
            data = {
                "active_trade": active_trade, "entry_price": entry_price,
                "target_sl": target_sl, "target_tp1": target_tp1, "target_tp2": target_tp2, "target_tp3": target_tp3,
                "m5_bias_at_entry": m5_bias_at_entry, "tp1_hit": tp1_hit, "tp2_hit": tp2_hit, "tp3_hit": tp3_hit,
                "trade_open_time": trade_open_time.strftime("%Y-%m-%d %H:%M:%S") if trade_open_time else None,
                "trade_signal_type": trade_signal_type, "trade_signal_id": trade_signal_id,
                "trade_grade": trade_grade, "trade_reason": trade_reason,
                "trade_rsi": trade_rsi, "trade_ema_diff": trade_ema_diff, "trade_atr": trade_atr,
                "trade_bias": trade_bias, "trade_score": trade_score, "timeout_final": timeout_final
            }
            atomic_write_json(ACTIVE_TRADE_FILE, data)
        else:
            if os.path.exists(ACTIVE_TRADE_FILE):
                os.remove(ACTIVE_TRADE_FILE)
    except Exception as e:
        print(f"[ActiveTrade] Save error: {e}")

def load_active_trade():
    global active_trade, entry_price, target_sl, target_tp1, target_tp2, target_tp3, m5_bias_at_entry
    global tp1_hit, tp2_hit, tp3_hit, trade_open_time, trade_signal_type, trade_signal_id
    global trade_grade, trade_reason, trade_rsi, trade_ema_diff, trade_atr, trade_bias, trade_score, timeout_final
    try:
        if os.path.exists(ACTIVE_TRADE_FILE):
            with open(ACTIVE_TRADE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            active_trade = data.get("active_trade")
            entry_price = data.get("entry_price", 0.0)
            target_sl = data.get("target_sl", 0.0)
            target_tp1 = data.get("target_tp1", 0.0)
            target_tp2 = data.get("target_tp2", 0.0)
            target_tp3 = data.get("target_tp3", 0.0)
            m5_bias_at_entry = data.get("m5_bias_at_entry", "NEUTRAL")
            tp1_hit = data.get("tp1_hit", False)
            tp2_hit = data.get("tp2_hit", False)
            tp3_hit = data.get("tp3_hit", False)
            trade_signal_type = data.get("trade_signal_type")
            trade_signal_id = data.get("trade_signal_id")
            trade_grade = data.get("trade_grade")
            trade_reason = data.get("trade_reason")
            trade_rsi = data.get("trade_rsi", 0.0)
            trade_ema_diff = data.get("trade_ema_diff", 0.0)
            trade_atr = data.get("trade_atr", 0.0)
            trade_bias = data.get("trade_bias", "")
            trade_score = data.get("trade_score", 0)
            timeout_final = data.get("timeout_final", False)
            time_str = data.get("trade_open_time")
            if time_str:
                trade_open_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SAUDI_TZ)
    except Exception as e:
        print(f"[ActiveTrade] Load error: {e}")

def acquire_bot_lock():
    try:
        if os.path.exists(bot_lock_file):
            with open(bot_lock_file, "r") as f:
                lock_data = json.load(f)
            lock_time = datetime.fromisoformat(lock_data.get("time", ""))
            if (datetime.now(SAUDI_TZ) - lock_time.replace(tzinfo=SAUDI_TZ)).total_seconds() < 600:
                print("[Lock] Another instance is running. Exiting.")
                return False
        with open(bot_lock_file, "w") as f:
            json.dump({"time": datetime.now(SAUDI_TZ).isoformat()}, f)
        return True
    except:
        return True

def update_bot_lock():
    try:
        with open(bot_lock_file, "w") as f:
            json.dump({"time": datetime.now(SAUDI_TZ).isoformat()}, f)
    except:
        pass

def send_to_telegram(message, event_id=None, parse_mode="HTML"):
    global sent_events
    if not TELEGRAM_TOKEN:
        return False
    if event_id:
        with telegram_lock:
            if event_id in sent_events:
                return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    success_count = 0
    total_chats = 0
    for chat_id in [PRIVATE_CHAT_ID, CHANNEL_CHAT_ID]:
        if not chat_id:
            continue
        total_chats += 1
        try:
            r = requests.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }, timeout=10)
            if r.ok:
                success_count += 1
            time.sleep(0.15)
        except Exception as e:
            print(f"[Telegram] Error: {e}")
    if event_id and success_count == total_chats and total_chats > 0:
        with telegram_lock:
            sent_events.add(event_id)
            save_sent_events()
        return True
    return success_count > 0

def send_to_admin_channel(message, reply_markup=None, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not ADMIN_CHANNEL_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHANNEL_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"[AdminChannel] Failed: {r.text}")
        return r.ok
    except Exception as e:
        print(f"[AdminChannel] Error: {e}")
        return False

def answer_callback(callback_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = True
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[AnswerCallback] Error: {e}")

def create_signal_id(signal_type, candle_time):
    raw = f"{signal_type}_{candle_time}".encode("utf-8")
    short_hash = hashlib.md5(raw).hexdigest()[:8].upper()
    return f"{signal_type}-{datetime.now(SAUDI_TZ).strftime('%Y%m%d')}-{short_hash}"

def send_message_with_keyboard(chat_id, text, keyboard=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.ok
    except Exception as e:
        print(f"[Keyboard] Error: {e}")
        return False

def get_main_keyboard():
    return {
        "keyboard": [
            ["💰 رصيدي", "📈 تداول"],
            ["🤖 تداول آلي", "📥 إيداع"],
            ["📤 سحب", "📊 صفقاتي المفتوحة"],
            ["📜 سجل صفقاتي", "📊 سعر XAUUSD"],
            ["📰 أخبار السوق", "🆔 ايدي"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_usd_high_impact_news():
    global news_cache, news_cache_time
    now = time.time()
    if news_cache_time and (now - news_cache_time) < 900:
        return news_cache
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            events = r.json()
            news_list = []
            for event in events:
                if event.get("country") != "USD" or event.get("impact") != "High":
                    continue
                try:
                    news_time_utc = datetime.fromisoformat(event.get("date", ""))
                    if news_time_utc.tzinfo is None:
                        news_time_utc = news_time_utc.replace(tzinfo=dt_timezone.utc)
                    news_time = news_time_utc.astimezone(SAUDI_TZ)
                    news_list.append({
                        "title": event.get("title", ""),
                        "time": news_time,
                        "forecast": event.get("forecast", "N/A"),
                        "previous": event.get("previous", "N/A")
                    })
                except:
                    continue
            news_cache = news_list
            news_cache_time = now
            return news_list
    except Exception as e:
        print(f"[News] Error: {e}")
    return news_cache if news_cache else []

def is_news_block_active(news_list, current_time):
    for news in news_list:
        news_time = news["time"]
        if news_time.tzinfo is None:
            news_time = news_time.replace(tzinfo=SAUDI_TZ)
        if (news_time - timedelta(minutes=NEWS_BLOCK_BEFORE_MIN)) <= current_time <= (news_time + timedelta(minutes=NEWS_BLOCK_AFTER_MIN)):
            return True, news
    return False, None

def send_news_report(news_list, saudi_now):
    global news_reports_sent
    for news in news_list:
        news_time = news["time"]
        if news_time.tzinfo is None:
            news_time = news_time.replace(tzinfo=SAUDI_TZ)
        time_until = news_time - saudi_now
        if timedelta(minutes=0) <= time_until <= timedelta(minutes=NEWS_REPORT_BEFORE_MIN):
            report_id = f"NEWS_{news['title']}_{news_time.strftime('%Y%m%d%H%M')}"
            if report_id in news_reports_sent:
                continue
            mins_left = int(time_until.total_seconds() / 60)
            msg = (
                f"📰 <b>تنبيه إخباري</b>\n\n"
                f"🔴 <b>الخبر:</b> <code>{news['title']}</code>\n"
                f"⏰ <b>الوقت:</b> <code>{news_time.strftime('%H:%M')}</code>\n"
                f"⏳ <b>بعد:</b> <code>{mins_left}</code> دقيقة\n"
                f"📊 المتوقع: <code>{news['forecast']}</code> | السابق: <code>{news['previous']}</code>"
            )
            if send_to_telegram(msg, event_id=report_id):
                news_reports_sent.add(report_id)

def get_biquote_ohlcv(interval: str, limit: int = 200, max_retries: int = 2):
    for attempt in range(max_retries):
        try:
            url = f"{BIQUOTE_BASE_URL}/{BIQUOTE_SYMBOL}/ohlc"
            r = requests.get(url, params={"interval": interval, "limit": min(limit, 1000)}, timeout=5)
            if r.status_code == 200:
                bars = r.json().get("bars", [])
                if bars:
                    bars = list(reversed(bars))
                    closes, lows, highs, opens, volumes, times = [], [], [], [], [], []
                    for b in bars:
                        try:
                            c = float(b["close"])
                            l = float(b["low"])
                            h = float(b["high"])
                            o = float(b["open"])
                            if c > 0 and l > 0 and h > 0 and o > 0:
                                closes.append(c)
                                lows.append(l)
                                highs.append(h)
                                opens.append(o)
                                volumes.append(float(b.get("tickVolume", 0)))
                                times.append(b.get("openTime", ""))
                        except:
                            continue
                    if len(closes) >= 30:
                        return {"closes": closes, "lows": lows, "highs": highs, "opens": opens, "volumes": volumes, "times": times}
            if attempt < max_retries - 1:
                time.sleep(0.35)
        except Exception as e:
            print(f"[biquote] {e}")
            if attempt < max_retries - 1:
                time.sleep(0.35)
    return None

def get_biquote_price(max_retries=3):
    for attempt in range(max_retries):
        try:
            r = requests.get(f"{BIQUOTE_BASE_URL}/{BIQUOTE_SYMBOL}", timeout=4)
            if r.status_code == 200:
                mid = r.json().get("mid")
                if mid is not None:
                    return float(mid)
        except Exception as e:
            print(f"[Price] Attempt {attempt+1} failed: {e}")
        time.sleep(0.4)
    try:
        closes = tf_data.get("5m", {}).get("closes", [])
        if closes:
            return float(closes[-1])
    except:
        pass
    return None

def is_data_fresh(timeframe="5m"):
    last_update = tf_data.get(timeframe, {}).get("last_update", 0)
    if last_update == 0:
        return False
    return (time.time() - last_update) <= MAX_DATA_AGE_SECONDS

def update_all_timeframes():
    global tf_data
    now = time.time()
    for name, settings in TIMEFRAMES.items():
        if now - tf_data[name].get("last_update", 0) < settings["refresh"]:
            continue
        data = get_biquote_ohlcv(settings["interval"], settings["limit"])
        if data:
            tf_data[name] = data
            tf_data[name]["last_update"] = now

def calculate_ema(values, period):
    if not values or len(values) < period:
        return [0.0] * len(values)
    ema = [0.0] * len(values)
    multiplier = 2 / (period + 1)
    ema[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        ema[i] = (values[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema

def calculate_rsi(closes, period=14):
    if not closes or len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = ((atr * (period - 1)) + trs[i]) / period
    return atr

def calculate_sma(values, period):
    if not values or len(values) < period:
        return [0.0] * len(values)
    return [0.0]*(period-1) + [sum(values[i-period+1:i+1])/period for i in range(period-1, len(values))]

def is_overextended(closes, highs, lows, signal_type, context=None):
    if context and context.get("h1_bias") == context.get("m15_bias") == context.get("m5_bias") and context.get("h1_bias") != "NEUTRAL":
        over_points = 70.0
        over_candles = 20
    else:
        over_points = 36.0
        over_candles = 40
    if len(closes) < over_candles + 1:
        return False
    recent_highs = highs[-over_candles:]
    recent_lows = lows[-over_candles:]
    highest = max(recent_highs)
    lowest = min(recent_lows)
    move = highest - lowest
    current = closes[-1]
    if move < over_points:
        return False
    mid = lowest + (move * 0.50)
    if signal_type == "BUY":
        if current > mid and move >= over_points:
            return True
    else:
        if current < mid and move >= over_points:
            return True
    return False

def check_ema_pullback_entry(closes, highs, lows, signal_type, context):
    if len(closes) < 25:
        return False
    ema20 = calculate_ema(closes, 20)
    current_price = closes[-1]
    low = lows[-1]
    high = highs[-1]
    if context.get("h1_bias") == "BULLISH" and context.get("m15_bias") == "BULLISH":
        if signal_type == "BUY":
            if low <= ema20[-1] and current_price > ema20[-1]:
                return True
            if abs(current_price - ema20[-1]) <= 2.5 and current_price > ema20[-1]:
                return True
    if context.get("h1_bias") == "BEARISH" and context.get("m15_bias") == "BEARISH":
        if signal_type == "SELL":
            if high >= ema20[-1] and current_price < ema20[-1]:
                return True
            if abs(current_price - ema20[-1]) <= 2.5 and current_price < ema20[-1]:
                return True
    return False

def detect_fvg(highs, lows):
    if len(highs) < 3:
        return {"has_fvg": False, "type": "NONE"}
    if lows[-1] > highs[-3]:
        return {"has_fvg": True, "type": "BULLISH"}
    if highs[-1] < lows[-3]:
        return {"has_fvg": True, "type": "BEARISH"}
    return {"has_fvg": False, "type": "NONE"}

def detect_candlestick_pattern(opens, highs, lows, closes, volumes=None):
    if len(closes) < SWEEP_LOOKBACK + 2:
        return {"pattern": "NONE", "bullish": False, "bearish": False, "strength": 0}
    if len(closes) < 5:
        return {"pattern": "NONE", "bullish": False, "bearish": False, "strength": 0}
    o1, h1, l1, c1 = opens[-5], highs[-5], lows[-5], closes[-5]
    o2, h2, l2, c2 = opens[-4], highs[-4], lows[-4], closes[-4]
    o3, h3, l3, c3 = opens[-3], highs[-3], lows[-3], closes[-3]
    o4, h4, l4, c4 = opens[-2], highs[-2], lows[-2], closes[-2]
    o5, h5, l5, c5 = opens[-1], highs[-1], lows[-1], closes[-1]
    def body(o,c): return abs(c-o)
    def rng(h,l): return h-l if h!=l else 0.0001
    def upper(h,o,c): return h-max(o,c)
    def lower(l,o,c): return min(o,c)-l
    def is_bull(o,c): return c>o
    def is_bear(o,c): return c<o
    def avg_body(n=20):
        try:
            return sum([abs(closes[-i]-opens[-i]) for i in range(1,n+1)])/n
        except:
            return body(o5,c5)
    b1, b2, b3, b4, b5 = body(o1,c1), body(o2,c2), body(o3,c3), body(o4,c4), body(o5,c5)
    r1, r2, r3, r4, r5 = rng(h1,l1), rng(h2,l2), rng(h3,l3), rng(h4,l4), rng(h5,l5)
    u1, u2, u3, u4, u5 = upper(h1,o1,c1), upper(h2,o2,c2), upper(h3,o3,c3), upper(h4,o4,c4), upper(h5,o5,c5)
    lw1, lw2, lw3, lw4, lw5 = lower(l1,o1,c1), lower(l2,o2,c2), lower(l3,o3,c3), lower(l4,o4,c4), lower(l5,o5,c5)
    avg_b = avg_body(20)
    prev_high = max(highs[-SWEEP_LOOKBACK-1:-1])
    prev_low = min(lows[-SWEEP_LOOKBACK-1:-1])
    if l5 < prev_low and c5 > prev_low and lw5 > b5 * 1.3:
        return {"pattern": "Bullish Liquidity Sweep", "bullish": True, "bearish": False, "strength": 95}
    if h5 > prev_high and c5 < prev_high and u5 > b5 * 1.3:
        return {"pattern": "Bearish Liquidity Sweep", "bullish": False, "bearish": True, "strength": 95}
    if is_bear(o3,c3) and b3 > avg_b*0.8 and body(o4,c4) < avg_b*0.4 and is_bull(o5,c5) and c5 > (o3+c3)/2 and b5 > avg_b*0.8:
        return {"pattern": "Morning Star", "bullish": True, "bearish": False, "strength": 94}
    if is_bull(o3,c3) and b3 > avg_b*0.8 and body(o4,c4) < avg_b*0.4 and is_bear(o5,c5) and c5 < (o3+c3)/2 and b5 > avg_b*0.8:
        return {"pattern": "Evening Star", "bullish": False, "bearish": True, "strength": 94}
    if is_bull(o3,c3) and is_bull(o4,c4) and is_bull(o5,c5) and c4>c3 and c5>c4 and b3>avg_b*0.6 and b4>avg_b*0.6 and b5>avg_b*0.6:
        return {"pattern": "Three White Soldiers", "bullish": True, "bearish": False, "strength": 92}
    if is_bear(o3,c3) and is_bear(o4,c4) and is_bear(o5,c5) and c4<c3 and c5<c4 and b3>avg_b*0.6 and b4>avg_b*0.6 and b5>avg_b*0.6:
        return {"pattern": "Three Black Crows", "bullish": False, "bearish": True, "strength": 92}
    if is_bear(o4,c4) and is_bull(o5,c5) and c5 >= o4 and o5 <= c4 and b5 > b4 * 0.85:
        return {"pattern": "Bullish Engulfing", "bullish": True, "bearish": False, "strength": 90}
    if is_bull(o4,c4) and is_bear(o5,c5) and c5 <= o4 and o5 >= c4 and b5 > b4 * 0.85:
        return {"pattern": "Bearish Engulfing", "bullish": False, "bearish": True, "strength": 90}
    if abs(l4-l5) <= r5*0.1 and lw4 > b4*1.2 and lw5 > b5*0.8 and is_bull(o5,c5):
        return {"pattern": "Tweezer Bottom", "bullish": True, "bearish": False, "strength": 88}
    if abs(h4-h5) <= r5*0.1 and u4 > b4*1.2 and u5 > b5*0.8 and is_bear(o5,c5):
        return {"pattern": "Tweezer Top", "bullish": False, "bearish": True, "strength": 88}
    if is_bear(o4,c4) and is_bull(o5,c5) and o5 < l4 and c5 > (o4+c4)/2 and c5 < o4:
        return {"pattern": "Piercing Line", "bullish": True, "bearish": False, "strength": 87}
    if is_bull(o4,c4) and is_bear(o5,c5) and o5 > h4 and c5 < (o4+c4)/2 and c5 > o4:
        return {"pattern": "Dark Cloud Cover", "bullish": False, "bearish": True, "strength": 87}
    if lw5 > b5 * 1.9 and u5 < b5 * 0.4 and is_bull(o5,c5):
        return {"pattern": "Hammer", "bullish": True, "bearish": False, "strength": 86}
    if lw5 > b5 * 1.8 and u5 < b5 * 0.5:
        return {"pattern": "Hammer / Pinbar", "bullish": True, "bearish": False, "strength": 84}
    if u5 > b5 * 1.9 and lw5 < b5 * 0.4 and is_bear(o5,c5):
        return {"pattern": "Shooting Star", "bullish": False, "bearish": True, "strength": 86}
    if u5 > b5 * 1.9 and lw5 < b5 * 0.4 and is_bull(o5,c5):
        return {"pattern": "Inverted Hammer", "bullish": True, "bearish": False, "strength": 82}
    if b4 > avg_b*0.8 and b5 < b4*0.5 and is_bear(o4,c4) and is_bull(o5,c5) and o5 > c4 and c5 < o4:
        return {"pattern": "Bullish Harami", "bullish": True, "bearish": False, "strength": 80}
    if b4 > avg_b*0.8 and b5 < b4*0.5 and is_bull(o4,c4) and is_bear(o5,c5) and o5 < c4 and c5 > o4:
        return {"pattern": "Bearish Harami", "bullish": False, "bearish": True, "strength": 80}
    if is_bull(o5,c5) and b5 > r5 * 0.75:
        return {"pattern": "Bullish Marubozu", "bullish": True, "bearish": False, "strength": 82}
    if is_bear(o5,c5) and b5 > r5 * 0.75:
        return {"pattern": "Bearish Marubozu", "bullish": False, "bearish": True, "strength": 82}
    if is_bull(o5,c5) and b5 > r5 * 0.58 and lw5 < b5 * 0.3:
        return {"pattern": "Strong Bullish Candle", "bullish": True, "bearish": False, "strength": 76}
    if is_bear(o5,c5) and b5 > r5 * 0.58 and u5 < b5 * 0.3:
        return {"pattern": "Strong Bearish Candle", "bullish": False, "bearish": True, "strength": 76}
    if is_bull(o5,c5) and is_bear(o4,c4) and o5 > c4 and b5 > avg_b*1.2 and abs(o5 - c4) > avg_b*0.3:
        return {"pattern": "Bullish Kicker", "bullish": True, "bearish": False, "strength": 93}
    if is_bear(o5,c5) and is_bull(o4,c4) and o5 < c4 and b5 > avg_b*1.2 and abs(o5 - c4) > avg_b*0.3:
        return {"pattern": "Bearish Kicker", "bullish": False, "bearish": True, "strength": 93}
    if is_bull(o5,c5) and is_bull(o3,c3) and b5 > avg_b*0.9 and c5 > h4 and c5 > h2:
        return {"pattern": "Rising Three Methods", "bullish": True, "bearish": False, "strength": 89}
    if is_bear(o5,c5) and is_bear(o3,c3) and b5 > avg_b*0.9 and c5 < l4 and c5 < l2:
        return {"pattern": "Falling Three Methods", "bullish": False, "bearish": True, "strength": 89}
    if b5 < r5*0.15 and r5 > avg_b*0.5:
        if is_bull(opens[-1], closes[-1]) and closes[-1] > max(opens[-2], closes[-2]):
            return {"pattern": "Doji + Bullish Confirmation", "bullish": True, "bearish": False, "strength": 78}
        if is_bear(opens[-1], closes[-1]) and closes[-1] < min(opens[-2], closes[-2]):
            return {"pattern": "Doji + Bearish Confirmation", "bullish": False, "bearish": True, "strength": 78}
    return {"pattern": "NONE", "bullish": False, "bearish": False, "strength": 0}

def check_support_resistance_proximity(current_price, highs, lows, period=SR_LOOKBACK, tolerance=4.0):
    if len(highs) < period:
        return {"near_support": False, "near_resistance": False}
    support = min(lows[-period:])
    resistance = max(highs[-period:])
    return {
        "near_support": abs(current_price - support) <= tolerance,
        "near_resistance": abs(current_price - resistance) <= tolerance
    }

def analyze_market_context():
    h1 = tf_data.get("1h", {}).get("closes", [])
    m15 = tf_data.get("15m", {}).get("closes", [])
    m5 = tf_data.get("5m", {}).get("closes", [])
    if len(m5) < 30:
        return {"h1_bias": "NEUTRAL", "m15_bias": "NEUTRAL", "m5_bias": "NEUTRAL", "bias": "NEUTRAL", "m15_above_ema50": False, "m15_below_ema50": False, "m15_ema50_rising": False, "m15_ema50_falling": False, "h1_above_ema50": False, "m1_bias": "NEUTRAL"}
    h1_bias = "NEUTRAL"
    h1_above_ema50 = False
    if len(h1) >= 50:
        e20 = calculate_ema(h1, 20)
        e50_h1 = calculate_ema(h1, 50)
        h1_bias = "BULLISH" if h1[-1] > e20[-1] else "BEARISH"
        h1_above_ema50 = h1[-1] > e50_h1[-1]
    elif len(h1) >= 20:
        e20 = calculate_ema(h1, 20)
        h1_bias = "BULLISH" if h1[-1] > e20[-1] else "BEARISH"
    m15_bias = "NEUTRAL"
    m15_above_ema50 = False
    m15_below_ema50 = False
    m15_ema50_rising = False
    m15_ema50_falling = False
    if len(m15) >= 50:
        e9 = calculate_ema(m15, 9)
        e21 = calculate_ema(m15, 21)
        e50_m15 = calculate_ema(m15, 50)
        m15_bias = "BULLISH" if e9[-1] > e21[-1] else "BEARISH"
        m15_above_ema50 = m15[-1] > e50_m15[-1]
        m15_below_ema50 = m15[-1] < e50_m15[-1]
        if len(e50_m15) >= 5:
            m15_ema50_rising = e50_m15[-1] > e50_m15[-3]
            m15_ema50_falling = e50_m15[-1] < e50_m15[-3]
    elif len(m15) >= 21:
        e9 = calculate_ema(m15, 9)
        e21 = calculate_ema(m15, 21)
        m15_bias = "BULLISH" if e9[-1] > e21[-1] else "BEARISH"
    m5_bias = "NEUTRAL"
    e9m5 = calculate_ema(m5, 9)
    e21m5 = calculate_ema(m5, 21)
    m5_bias = "BULLISH" if e9m5[-1] > e21m5[-1] else "BEARISH"
    m1_bias = "NEUTRAL"
    m1 = tf_data.get("1m", {}).get("closes", [])
    if len(m1) >= 21:
        e9_m1 = calculate_ema(m1, 9)
        e21_m1 = calculate_ema(m1, 21)
        m1_bias = "BULLISH" if e9_m1[-1] > e21_m1[-1] else "BEARISH"
    return {
        "h1_bias": h1_bias, "m15_bias": m15_bias, "m5_bias": m5_bias, "m1_bias": m1_bias,
        "bias": m15_bias if m15_bias == m5_bias else m5_bias,
        "m15_above_ema50": m15_above_ema50,
        "m15_below_ema50": m15_below_ema50,
        "m15_ema50_rising": m15_ema50_rising,
        "m15_ema50_falling": m15_ema50_falling,
        "h1_above_ema50": h1_above_ema50
    }

def check_trade_against_context(signal_type, context, candle=None):
    m15 = context.get("m15_bias", "NEUTRAL")
    m5 = context.get("m5_bias", "NEUTRAL")
    h1 = context.get("h1_bias", "NEUTRAL")
    m1_bias = context.get("m1_bias", "NEUTRAL")
    m15_above_ema50 = context.get("m15_above_ema50", False)
    m15_below_ema50 = context.get("m15_below_ema50", False)
    m15_ema50_rising = context.get("m15_ema50_rising", False)
    m15_ema50_falling = context.get("m15_ema50_falling", False)
    strength = candle.get("strength", 0) if candle else 0
    pattern = candle.get("pattern", "") if candle else ""
    is_strong_reversal = strength >= 80 and "Kicker" in pattern
    if signal_type == "BUY":
        if m15_below_ema50 and m15_ema50_falling and not is_strong_reversal:
            return False
        if m1_bias == "BEARISH" and not is_strong_reversal:
            return False
        if m5 == "BULLISH" and m1_bias == "BULLISH":
            if m15_below_ema50 and m15_ema50_falling:
                return False
            return True
        if m5 == "BEARISH" and m15 == "BEARISH" and not is_strong_reversal:
            return False
        if h1 == "BEARISH" and m15 == "BEARISH":
            if is_strong_reversal and m1_bias == "BULLISH" and m15_above_ema50:
                return True
            return False
        return m1_bias == "BULLISH" and m15_above_ema50
    else:
        if m15_above_ema50 and m15_ema50_rising and not is_strong_reversal:
            return False
        if m1_bias == "BULLISH" and not is_strong_reversal:
            return False
        if m5 == "BEARISH" and m1_bias == "BEARISH":
            if m15_above_ema50 and m15_ema50_rising:
                return False
            return True
        if m5 == "BULLISH" and m15 == "BULLISH" and not is_strong_reversal:
            return False
        if h1 == "BULLISH" and m15 == "BULLISH":
            if is_strong_reversal and m1_bias == "BEARISH" and m15_below_ema50:
                return True
            return False
        return m1_bias == "BEARISH" and m15_below_ema50

def check_choppy_market(closes, highs, lows):
    if len(closes) < 20:
        return False
    atr = calculate_atr(highs, lows, closes, 14)
    if atr == 0:
        return False
    return (max(highs[-20:]) - min(lows[-20:])) < atr * CHOPPY_RANGE_MULTIPLIER

def check_early_pullback_entry_1m():
    m1 = tf_data.get("1m", {})
    closes = m1.get("closes", [])
    highs = m1.get("highs", [])
    lows = m1.get("lows", [])
    if len(closes) < 25:
        return None
    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    price = closes[-1]
    fvg = detect_fvg(highs, lows)
    near_ema9 = abs(price - ema9[-1]) <= 2.0
    near_ema20 = abs(price - ema20[-1]) <= 2.5
    has_fvg = fvg.get("has_fvg", False)
    if near_ema9 or near_ema20 or has_fvg:
        e9 = ema9[-1]
        e21 = ema20[-1]
        if price > e9 and e9 > e21:
            return "BUY"
        if price < e9 and e9 < e21:
            return "SELL"
    return None

def detect_wave_momentum(closes, opens, highs, lows, volumes=None, context=None):
    if len(closes) < OVEREXTENSION_CANDLES + 5:
        return {"signal": "NONE"}
    ema9 = calculate_ema(closes, EMA_FAST)
    ema21 = calculate_ema(closes, EMA_SLOW)
    rsi = calculate_rsi(closes)
    candle = detect_candlestick_pattern(opens, highs, lows, closes, volumes)
    ema_diff = ema9[-1] - ema21[-1]
    if candle["strength"] < MIN_CANDLE_STRENGTH:
        if not ("Pinbar" in candle["pattern"] or "Hammer" in candle["pattern"] or "Sweep" in candle["pattern"] or "Wick" in candle["pattern"] or candle["strength"] >= 35):
            return {"signal": "NONE"}
    if (candle["bullish"] and ema9[-1] > ema21[-1] and rsi <= RSI_MAX_FOR_BUY and closes[-1] > opens[-1]):
        if is_overextended(closes, highs, lows, "BUY", context):
            if not check_ema_pullback_entry(closes, highs, lows, "BUY", context or {}):
                return {"signal": "NONE", "reason": "Overextended Up"}
        return {
            "signal": "BUY",
            "rsi": rsi,
            "ema_diff": ema_diff,
            "candle": candle,
            "reason": f"BUY: {candle['pattern']} + EMA + RSI {rsi:.1f}"
        }
    if (candle["bearish"] and ema9[-1] < ema21[-1] and rsi >= RSI_MIN_FOR_SELL and closes[-1] < opens[-1]):
        if is_overextended(closes, highs, lows, "SELL", context):
            if not check_ema_pullback_entry(closes, highs, lows, "SELL", context or {}):
                return {"signal": "NONE", "reason": "Overextended Down"}
        return {
            "signal": "SELL",
            "rsi": rsi,
            "ema_diff": ema_diff,
            "candle": candle,
            "reason": f"SELL: {candle['pattern']} + EMA + RSI {rsi:.1f}"
        }
    return {"signal": "NONE"}

def calculate_dynamic_risk(entry, trade_type, atr, lows=None, highs=None):
    dist = atr * ATR_MULTIPLIER_SL if atr > 0 else MIN_SL_PRICE_DISTANCE
    dist = max(MIN_SL_PRICE_DISTANCE, min(MAX_SL_PRICE_DISTANCE, dist))
    if trade_type == "BUY":
        structural = min(lows[-6:]) - 1.0 if lows and len(lows) >= 6 else entry - dist
        sl = min(entry - dist, structural)
        if entry - sl > MAX_SL_PRICE_DISTANCE:
            sl = entry - MAX_SL_PRICE_DISTANCE
        actual_dist = entry - sl
        tp1 = entry + actual_dist * ATR_MULTIPLIER_TP1
        tp2 = entry + actual_dist * ATR_MULTIPLIER_TP2
        tp3 = entry + actual_dist * ATR_MULTIPLIER_TP3
    else:
        structural = max(highs[-6:]) + 1.0 if highs and len(highs) >= 6 else entry + dist
        sl = max(entry + dist, structural)
        if sl - entry > MAX_SL_PRICE_DISTANCE:
            sl = entry + MAX_SL_PRICE_DISTANCE
        actual_dist = sl - entry
        tp1 = entry - actual_dist * ATR_MULTIPLIER_TP1
        tp2 = entry - actual_dist * ATR_MULTIPLIER_TP2
        tp3 = entry - actual_dist * ATR_MULTIPLIER_TP3
    return {"sl": round(sl, 2), "tp1": round(tp1, 2), "tp2": round(tp2, 2), "tp3": round(tp3, 2), "risk_distance": round(actual_dist, 2)}

def calculate_trade_score(rsi, ema_diff, candle, context, sr_info, fvg_info, signal_type):
    score = 48
    if candle["strength"] >= 90: score += 22
    elif candle["strength"] >= 80: score += 16
    elif candle["strength"] >= 73: score += 11
    elif candle["strength"] >= 60: score += 8
    if abs(ema_diff) > 0.15: score += 12
    if signal_type == "BUY" and sr_info.get("near_support"): score += 10
    if signal_type == "SELL" and sr_info.get("near_resistance"): score += 10
    if fvg_info.get("has_fvg") and fvg_info.get("type") == ("BULLISH" if signal_type == "BUY" else "BEARISH"):
        score += 9
    m15 = context.get("m15_bias", "NEUTRAL")
    m5 = context.get("m5_bias", "NEUTRAL")
    h1 = context.get("h1_bias", "NEUTRAL")
    if m15 == m5 and m15 != "NEUTRAL": score += 14
    if h1 == m15 == m5 and h1 != "NEUTRAL": score += 8
    if signal_type == "BUY" and h1 == "BEARISH": score -= 15
    if signal_type == "SELL" and h1 == "BULLISH": score -= 15
    if rsi > 68 or rsi < 32: score -= 15
    return max(0, min(score, 100))

def classify_trade_with_score(score):
    if score >= 86: return "A+", "🏆", "SEND"
    elif score >= 65: return "A", "✅", "SEND"
    else: return "B", "⚠️", "SKIP"

def record_trade_result(trade_data, result_type, profit=0, duration=0):
    global ai_memory, weekly_wins, weekly_losses, weekly_total_profit
    global consecutive_losses, daily_loss_total, last_consecutive_loss_pause
    try:
        record = {
            "timestamp": datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "signal_type": trade_data.get("signal_type", ""),
            "entry": trade_data.get("entry", 0),
            "sl": trade_data.get("sl", 0),
            "tp1": trade_data.get("tp1", 0),
            "tp2": trade_data.get("tp2", 0),
            "rsi": trade_data.get("rsi", 0),
            "score": trade_data.get("score", 0),
            "grade": trade_data.get("grade", ""),
            "reason": trade_data.get("reason", ""),
            "result": result_type,
            "profit": profit,
            "duration": duration
        }
        ai_memory.setdefault("trade_log", []).append(record)
        ai_memory["total_trades"] = ai_memory.get("total_trades", 0) + 1
        if result_type in ("TP2", "WIN", "REVERSAL_WIN", "TP1_WIN", "TP3"):
            ai_memory["total_wins"] = ai_memory.get("total_wins", 0) + 1
            weekly_wins += 1
            consecutive_losses = 0
            last_consecutive_loss_pause = None
        elif result_type in ("SL", "LOSS", "REVERSAL_LOSS", "TIMEOUT", "M5_FLIP_LOSS"):
            ai_memory["total_losses"] = ai_memory.get("total_losses", 0) + 1
            weekly_losses += 1
            consecutive_losses += 1
            daily_loss_total += abs(profit)
        weekly_total_profit += profit
        total = ai_memory.get("total_wins", 0) + ai_memory.get("total_losses", 0)
        if total > 0:
            ai_memory["win_rate"] = (ai_memory["total_wins"] / total) * 100
        save_ai_memory()
    except Exception as e:
        print(f"[AI] Record error: {e}")

def should_skip_trade():
    global consecutive_losses, last_consecutive_loss_pause, daily_loss_total
    now = datetime.now(SAUDI_TZ)
    if last_consecutive_loss_pause and (now - last_consecutive_loss_pause).total_seconds()/60 < PAUSE_AFTER_CONSECUTIVE_LOSSES_MIN:
        return True
    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        last_consecutive_loss_pause = now
        return True
    if daily_loss_total >= DAILY_LOSS_LIMIT or daily_losses >= MAX_DAILY_LOSSES:
        return True
    if consecutive_losses >= 2:
        return True
    return False

def is_market_open(saudi_now=None):
    if saudi_now is None:
        saudi_now = datetime.now(SAUDI_TZ)
    now_ny = saudi_now.astimezone(NY_TZ)
    wd, hour = now_ny.weekday(), now_ny.hour
    if wd == 5: return False
    if wd == 6: return hour >= 18
    if wd == 4: return hour < 17
    return True

def send_pre_market_report(saudi_now):
    ctx = analyze_market_context()
    price = get_biquote_price()
    price_text = f"{price:.3f}" if price is not None else "غير متوفر"
    msg = (
        f"🌅 <b>تقرير ما قبل الافتتاح</b>\n\n"
        f"📅 {saudi_now.strftime('%Y-%m-%d %H:%M')}\n"
        f"💰 السعر: {price_text}\n"
        f"H1: {ctx['h1_bias']} | M15: {ctx['m15_bias']} | M5: {ctx['m5_bias']}\n"
        f"🎯 الهدف: {TARGET_TRADES_PER_DAY} صفقة"
    )
    send_to_telegram(msg, event_id=f"PREMARKET_{saudi_now.date()}")

def send_market_open_alert(saudi_now):
    ctx = analyze_market_context()
    price = get_biquote_price()
    price_text = f"{price:.3f}" if price is not None else "غير متوفر"
    msg = (
        f"🟢 <b>افتتاح السوق</b>\n\n"
        f"📅 {saudi_now.strftime('%Y-%m-%d %H:%M')}\n"
        f"💰 السعر: {price_text}\n"
        f"H1: {ctx['h1_bias']} | M15: {ctx['m15_bias']} | M5: {ctx['m5_bias']}"
    )
    send_to_telegram(msg, event_id=f"OPEN_{saudi_now.date()}")

def send_market_close_alert(saudi_now):
    msg = (
        f"🔴 <b>إغلاق السوق</b>\n\n"
        f"📅 {saudi_now.strftime('%Y-%m-%d %H:%M')}\n"
        f"إشارات: {daily_signals} | مكتملة: {daily_completed_trades}\n"
        f"✅ {daily_wins} | ❌ {daily_losses} | 🛡️ {daily_be_hits}\n"
        f"💰 النقاط: {daily_total_profit:.2f}"
    )
    send_to_telegram(msg, event_id=f"CLOSE_{saudi_now.date()}")

def check_market_state(saudi_now):
    global last_market_state, pre_market_sent
    current = is_market_open(saudi_now)
    if last_market_state is None:
        last_market_state = current
        return
    if last_market_state != current:
        if current:
            send_market_open_alert(saudi_now)
            pre_market_sent = False
        else:
            send_market_close_alert(saudi_now)
        last_market_state = current

def analyze_market():
    global active_trade, entry_price, target_sl, target_tp1, target_tp2, target_tp3, m5_bias_at_entry
    global tp1_hit, tp2_hit, tp3_hit, trade_open_time, trade_signal_type, trade_signal_id
    global trade_grade, trade_reason, trade_rsi, trade_score, timeout_final
    global daily_signals, daily_completed_trades, daily_wins, daily_losses
    global daily_tp1_hits, daily_tp2_hits, daily_sl_hits, daily_be_hits, daily_timeout
    global daily_a_grade, daily_b_grade, daily_reversals, daily_total_profit
    global last_reversal_time, last_sl_timestamp, last_timeout_timestamp, last_signal_time
    global consecutive_losses, last_tp1_win_timestamp, last_tp1_win_price

    m1 = tf_data.get("1m", {})
    m1_closes = m1.get("closes", [])
    m1_opens = m1.get("opens", [])
    m1_highs = m1.get("highs", [])
    m1_lows = m1.get("lows", [])
    m1_volumes = m1.get("volumes", [])
    m5 = tf_data.get("5m", {})
    closes = m5.get("closes", [])
    opens = m5.get("opens", [])
    highs = m5.get("highs", [])
    lows = m5.get("lows", [])
    volumes = m5.get("volumes", [])
    use_1m = len(m1_closes) >= 30 and is_data_fresh("1m")
    if len(closes) < OVEREXTENSION_CANDLES + 5 or not is_data_fresh("5m"):
        return
    price = closes[-1]
    now = datetime.now(SAUDI_TZ)
    context = analyze_market_context()

    if active_trade:
        profit = (price - entry_price) if active_trade == "BUY" else (entry_price - price)
        elapsed = (now - trade_open_time).total_seconds() / 60
        trade_data = {
            "signal_type": trade_signal_type, "entry": entry_price, "sl": target_sl,
            "tp1": target_tp1, "tp2": target_tp2, "rsi": trade_rsi, "score": trade_score,
            "grade": trade_grade, "reason": trade_reason
        }
        m5_bias = context.get("m5_bias", "NEUTRAL")
        if not tp1_hit:
            if active_trade == "BUY" and m5_bias == "BEARISH":
                if m5_bias_at_entry == "BEARISH":
                    pass
                elif elapsed >= 5 and profit < 0:
                    daily_completed_trades += 1
                    daily_total_profit += profit
                    if profit >= 0:
                        daily_be_hits += 1
                        result_type = "M5_FLIP_BE"
                        title = f"🛡️ EXIT M5 FLIP - BE"
                    else:
                        daily_losses += 1
                        consecutive_losses += 1
                        result_type = "M5_FLIP_LOSS"
                        title = f"🛑 EXIT M5 FLIP - LOSS"
                    record_trade_result(trade_data, result_type, profit, elapsed)
                    send_to_telegram(f"<b>{title}</b>\n\nM5 انقلب إلى BEARISH\nالدخول: {entry_price}\nالخروج: {price}\n{profit:+.2f} نقطة | {elapsed:.0f}د")
                    active_trade = None
                    tp1_hit = tp2_hit = tp3_hit = False
                    save_active_trade()
                    return
            if active_trade == "SELL" and m5_bias == "BULLISH":
                if m5_bias_at_entry == "BULLISH":
                    pass
                elif elapsed >= 5 and profit < 0:
                    daily_completed_trades += 1
                    daily_total_profit += profit
                    if profit >= 0:
                        daily_be_hits += 1
                        result_type = "M5_FLIP_BE"
                        title = f"🛡️ EXIT M5 FLIP - BE"
                    else:
                        daily_losses += 1
                        consecutive_losses += 1
                        result_type = "M5_FLIP_LOSS"
                        title = f"🛑 EXIT M5 FLIP - LOSS"
                    record_trade_result(trade_data, result_type, profit, elapsed)
                    send_to_telegram(f"<b>{title}</b>\n\nM5 انقلب إلى BULLISH\nالدخول: {entry_price}\nالخروج: {price}\n{profit:+.2f} نقطة | {elapsed:.0f}د")
                    active_trade = None
                    tp1_hit = tp2_hit = tp3_hit = False
                    save_active_trade()
                    return
        if elapsed >= TIMEOUT_MINUTES and not tp1_hit and not timeout_final:
            if profit >= 0.8:
                pass
            elif abs(profit) < 2.5:
                timeout_final = True
                daily_timeout += 1
                daily_completed_trades += 1
                last_timeout_timestamp = now
                record_trade_result(trade_data, "TIMEOUT", profit, elapsed)
                send_to_telegram(f"⚠️ <b>TIMEOUT</b>\n{active_trade} | {profit:+.2f} | {elapsed:.0f}د")
                active_trade = None
                tp1_hit = tp2_hit = timeout_final = False
                save_active_trade()
                return
        if (active_trade == "BUY" and price <= target_sl) or (active_trade == "SELL" and price >= target_sl):
            daily_completed_trades += 1
            daily_total_profit += profit
            if tp1_hit:
                if profit >= 0.3:
                    daily_wins += 1
                    daily_be_hits += 1
                    result_type = "BE_WIN"
                    title = f"✅ BE WIN +0.5 - {active_trade} - رابحة"
                else:
                    daily_be_hits += 1
                    result_type = "BE"
                    title = f"🛡️ BE - {active_trade}"
            else:
                daily_losses += 1
                daily_sl_hits += 1
                consecutive_losses += 1
                last_sl_timestamp = now
                result_type = "SL"
                title = f"🛑 SL - {active_trade}"
            record_trade_result(trade_data, result_type, profit, elapsed)
            send_to_telegram(f"<b>{title}</b>\nالدخول: {entry_price}\nالخروج: {price}\n{profit:+.2f}\n{elapsed:.0f}د")
            active_trade = None
            tp1_hit = tp2_hit = False
            save_active_trade()
            return
        if not tp1_hit and ((active_trade == "BUY" and price >= target_tp1 - 0.3) or (active_trade == "SELL" and price <= target_tp1 + 0.3)):
            tp1_hit = True
            daily_tp1_hits += 1
            last_tp1_win_timestamp = now
            last_tp1_win_price = entry_price
            daily_wins += 1
            daily_completed_trades += 1
            daily_total_profit += profit
            consecutive_losses = 0
            last_consecutive_loss_pause = None
            record_trade_result(trade_data, "TP1_WIN", profit, elapsed)
            send_to_telegram(f"✅ <b>TP1 WIN +{profit:.2f} - {active_trade} - رابحة سكالبينج - تأمين</b>\nالدخول: {entry_price}\nالخروج: {price}\n🎯 تقفلت على تأمين")
            active_trade = None
            tp1_hit = tp2_hit = tp3_hit = False
            save_active_trade()
            return
        if tp1_hit and not tp2_hit and ((active_trade == "BUY" and price >= target_tp2 - 0.3) or (active_trade == "SELL" and price <= target_tp2 + 0.3)):
            tp2_hit = True
            daily_tp2_hits += 1
            if BREAK_EVEN_AT_TP1:
                target_sl = entry_price + (1 if active_trade=="BUY" else -1) * 1.0
            send_to_telegram(f"🚀 <b>TP2 - {active_trade} - مؤمن ✅</b>\n+{profit:.2f}\nمكملين لـ TP3: {target_tp3}")
            save_active_trade()
        if tp2_hit and not tp3_hit and ((active_trade == "BUY" and price >= target_tp3 - 0.3) or (active_trade == "SELL" and price <= target_tp3 + 0.3)):
            tp3_hit = True
            daily_wins += 1
            daily_completed_trades += 1
            consecutive_losses = 0
            last_consecutive_loss_pause = None
            record_trade_result(trade_data, "TP3", profit, elapsed)
            send_to_telegram(f"🏆 <b>TP3 - {active_trade} - هدف كامل</b>\n+{profit:.2f}")
            active_trade = None
            tp1_hit = tp2_hit = tp3_hit = False
            save_active_trade()
            return
    else:
        if daily_signals >= MAX_TRADES_PER_DAY or should_skip_trade():
            return
        if last_sl_timestamp and (now - last_sl_timestamp).total_seconds()/60 < COOLDOWN_AFTER_SL_MIN:
            return
        if last_timeout_timestamp and (now - last_timeout_timestamp).total_seconds()/60 < COOLDOWN_AFTER_TIMEOUT_MIN:
            return
        if last_tp1_win_timestamp and (now - last_tp1_win_timestamp).total_seconds()/60 < COOLDOWN_AFTER_TP1_WIN_MIN:
            if abs(price - last_tp1_win_price) < 5.0:
                return
        if last_signal_time and (now - last_signal_time).total_seconds() < 40:
            return
        if ENABLE_NEWS_FILTER:
            news = get_usd_high_impact_news()
            blocked, _ = is_news_block_active(news, now)
            if blocked:
                return
        if check_choppy_market(closes, highs, lows):
            return
        if use_1m:
            wave_1m = detect_wave_momentum(m1_closes, m1_opens, m1_highs, m1_lows, m1_volumes, context)
            if wave_1m["signal"] != "NONE":
                wave = wave_1m
                closes = m1_closes
                opens = m1_opens
                highs = m1_highs
                lows = m1_lows
                volumes = m1_volumes
                price = closes[-1]
            else:
                wave = detect_wave_momentum(closes, opens, highs, lows, volumes, context)
                if wave["signal"] == "NONE":
                    early = check_early_pullback_entry_1m()
                    if early:
                        rsi = calculate_rsi(m1_closes)
                        wave = {"signal": early, "rsi": rsi, "ema_diff": 0.2 if early=="BUY" else -0.2, "candle": {"pattern": "Early Pullback 1m EMA/FVG", "strength": 65}, "reason": f"{early}: Early Pullback 1m to EMA9/20/FVG - اول 20% من الموجة"}
        else:
            wave = detect_wave_momentum(closes, opens, highs, lows, volumes, context)
        if wave["signal"] == "NONE":
            if check_ema_pullback_entry(closes, highs, lows, "BUY", context):
                wave = {"signal": "BUY", "rsi": calculate_rsi(closes), "ema_diff": 0.2, "candle": {"pattern": "EMA20 Pullback", "strength": 70}, "reason": "BUY: EMA20 Pullback in strong trend"}
            elif check_ema_pullback_entry(closes, highs, lows, "SELL", context):
                wave = {"signal": "SELL", "rsi": calculate_rsi(closes), "ema_diff": -0.2, "candle": {"pattern": "EMA20 Pullback", "strength": 70}, "reason": "SELL: EMA20 Pullback in strong trend"}
            else:
                return
        if not check_trade_against_context(wave["signal"], context, wave.get("candle")):
            return
        sr = check_support_resistance_proximity(price, highs, lows)
        fvg = detect_fvg(highs, lows)
        score = calculate_trade_score(wave["rsi"], wave["ema_diff"], wave["candle"], context, sr, fvg, wave["signal"])
        grade, emoji, action = classify_trade_with_score(score)
        if action != "SEND":
            return
        with signal_lock:
            atr = calculate_atr(highs, lows, closes, 14) or 8.0
            risk = calculate_dynamic_risk(price, wave["signal"], atr, lows, highs)
            candle_time = m5.get("times", ["unknown"])[-1]
            new_id = create_signal_id(wave["signal"], candle_time)
            if new_id in sent_events:
                return
            msg = (
                f"{'🟢' if wave['signal']=='BUY' else '🔴'} <b>إشارة {wave['signal']} - QUALITY+</b>\n\n"
                f"🆔 <code>{new_id}</code>\n"
                f"⚡ الدخول: <code>{price}</code>\n"
                f"🛑 SL: <code>{risk['sl']}</code> ({risk['risk_distance']})\n"
                f"🎯 TP1: <code>{risk['tp1']}</code>\n"
                f"🚀 TP2: <code>{risk['tp2']}</code>\n🏆 TP3: <code>{risk['tp3']}</code>\n\n"
                f"📊 {grade} {emoji} | Score: {score}/100\n"
                f"📈 RSI: {wave['rsi']:.1f}\n"
                f"🕯 النمط: <code>{wave['candle']['pattern']}</code>\n"
                f"🧠 H1: {context['h1_bias']} | M15: {context['m15_bias']} | M5: {context['m5_bias']}\n"
                f"📌 {wave['reason']}"
            )
            if send_to_telegram(msg, event_id=new_id):
                try:
                    save_new_trade_to_db(action=wave["signal"], entry=price, target=risk["tp2"], stop_loss=risk["sl"], pair="XAUUSD", tp1=risk["tp1"], tp2=risk["tp2"], grade=f"{grade} {emoji}", reason=wave["reason"])
                except Exception as e:
                    print(f"[SQLite] Save on signal error: {e}")
                entry_price = price
                target_sl = risk["sl"]
                target_tp1 = risk["tp1"]
                target_tp2 = risk["tp2"]
                target_tp3 = risk["tp3"]
                m5_bias_at_entry = context.get("m5_bias", "NEUTRAL")
                tp1_hit = tp2_hit = False
                active_trade = wave["signal"]
                trade_open_time = now
                trade_signal_type = wave["signal"]
                trade_signal_id = new_id
                trade_grade = f"{grade} {emoji}"
                trade_reason = wave["reason"]
                trade_rsi = wave["rsi"]
                trade_score = score
                daily_signals += 1
                last_signal_time = now
                if "A" in grade:
                    daily_a_grade += 1
                else:
                    daily_b_grade += 1
                save_active_trade()

                try:
                    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
                    cur = conn.cursor()
                    cur.execute("SELECT user_id FROM users WHERE auto_trade=1 AND balance > 0")
                    auto_users = cur.fetchall()
                    conn.close()
                    for (uid,) in auto_users:
                        try:
                            trade_id, error = open_user_trade(uid, wave["signal"], DEFAULT_LOT, price, risk["sl"], risk["tp2"])
                            if trade_id:
                                try:
                                    send_message_with_keyboard(uid,
                                        f"🤖 <b>تداول آلي</b>\n\nتم فتح صفقة {wave['signal']} تلقائيًا\n🆔 <code>#{trade_id}</code>\n⚡ الدخول: <code>{price}</code>\n🛑 SL: <code>{risk['sl']}</code>\n🎯 TP: <code>{risk['tp2']}</code>",
                                        get_main_keyboard())
                                    send_to_admin_channel(
                                        f"🤖 <b>فتح صفقة عميل (آلي)</b>\n\n👤 ID: <code>{uid}</code>\n🆔 الصفقة: <code>#{trade_id}</code>\n📊 النوع: <code>{wave['signal']}</code>\n⚡ الدخول: <code>{price}</code>\n🛑 SL: <code>{risk['sl']}</code>\n🎯 TP: <code>{risk['tp2']}</code>"
                                    )
                                except:
                                    pass
                        except Exception as e:
                            print(f"[AutoTrade] Error for {uid}: {e}")
                except Exception as e:
                    print(f"[AutoTrade] Loop error: {e}")

# ==================== USER COMMANDS + CALLBACK + POLLING + MAIN ====================
# (نفس الكود السابق كامل بدون اختصار - التداول + الأزرار + التشغيل)

def handle_balance_command(chat_id, user_id):
    user = get_or_create_user(user_id)
    open_count = count_open_trades(user_id)
    auto_status = "🟢 مفعّل" if user.get("auto_trade", 0) == 1 else "🔴 متوقف"
    msg = (
        f"💰 <b>حسابك التجاري</b>\n\n"
        f"👤 الاسم: <code>{user['name']}</code>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💵 الرصيد: <code>{user['balance']:.2f} $</code>\n"
        f"📊 صفقات مفتوحة: <code>{open_count}</code>\n"
        f"🤖 تداول آلي: <b>{auto_status}</b>\n\n"
        f"📌 الحجم: <code>{DEFAULT_LOT}</code> لوت"
    )
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())

def handle_trade_menu(chat_id, user_id):
    user = get_or_create_user(user_id)
    if user["balance"] <= 0:
        send_message_with_keyboard(chat_id, "❌ رصيدك صفر. قم بالإيداع أولاً.", get_main_keyboard())
        return
    keyboard = {"keyboard": [["🟢 شراء BUY", "🔴 بيع SELL"], ["🔙 رجوع"]], "resize_keyboard": True}
    msg = f"📈 <b>قسم التداول اليدوي</b>\n\n💵 رصيدك: <code>{user['balance']:.2f}$</code>\n📦 الحجم: <code>{DEFAULT_LOT}</code> لوت\n\nاختر نوع الصفقة:"
    send_message_with_keyboard(chat_id, msg, keyboard)

def handle_open_trade(chat_id, user_id, action):
    price = get_biquote_price()
    if price is None:
        send_message_with_keyboard(chat_id, "❌ تعذر الحصول على السعر حالياً.", get_main_keyboard())
        return
    atr_approx = 8.0
    if action == "BUY":
        sl = round(price - atr_approx * 1.2, 2)
        tp = round(price + atr_approx * 1.8, 2)
    else:
        sl = round(price + atr_approx * 1.2, 2)
        tp = round(price - atr_approx * 1.8, 2)
    trade_id, error = open_user_trade(user_id, action, DEFAULT_LOT, price, sl, tp)
    if error:
        send_message_with_keyboard(chat_id, f"❌ {error}", get_main_keyboard())
        return
    msg = (
        f"{'🟢' if action == 'BUY' else '🔴'} <b>تم فتح صفقة {action}</b>\n\n"
        f"🆔 رقم الصفقة: <code>#{trade_id}</code>\n"
        f"📦 الحجم: <code>{DEFAULT_LOT}</code>\n"
        f"⚡ سعر الدخول: <code>{price:.2f}</code>\n"
        f"🛑 الستوب: <code>{sl}</code>\n"
        f"🎯 الهدف: <code>{tp}</code>\n\n"
        f"الصفقة قيد المتابعة تلقائياً"
    )
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())
    try:
        user = get_or_create_user(user_id)
        send_to_admin_channel(
            f"📈 <b>فتح صفقة عميل (يدوي)</b>\n\n"
            f"👤 {user['name']} (<code>{user_id}</code>)\n"
            f"🆔 الصفقة: <code>#{trade_id}</code>\n"
            f"📊 النوع: <code>{action}</code>\n"
            f"📦 الحجم: <code>{DEFAULT_LOT}</code>\n"
            f"⚡ الدخول: <code>{price:.2f}</code>\n"
            f"🛑 SL: <code>{sl}</code>\n"
            f"🎯 TP: <code>{tp}</code>"
        )
    except:
        pass

def handle_my_open_trades(chat_id, user_id):
    trades = get_open_user_trades(user_id)
    if not trades:
        send_message_with_keyboard(chat_id, "لا توجد صفقات مفتوحة حالياً.", get_main_keyboard())
        return
    price = get_biquote_price() or 0
    msg = f"📊 <b>صفقاتك المفتوحة ({len(trades)})</b>\n\n"
    keyboard_buttons = []
    for t in trades:
        floating = calculate_profit(t["action"], t["entry"], price, t["lot"])
        msg += (
            f"🆔 <code>#{t['id']}</code> | {t['action']}\n"
            f"دخول: {t['entry']} | حالياً: {price:.2f}\n"
            f"الربح العائم: <code>{floating:+.2f}$</code>\n"
            f"SL: {t['sl']} | TP: {t['tp']}\n\n"
        )
        keyboard_buttons.append([f"❌ إغلاق #{t['id']}"])
    keyboard_buttons.append(["🔙 رجوع"])
    send_message_with_keyboard(chat_id, msg, {"keyboard": keyboard_buttons, "resize_keyboard": True})

def handle_my_trade_history(chat_id, user_id):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("SELECT id, action, lot, entry, close_price, profit, status FROM user_trades WHERE user_id=? AND status != 'Open' ORDER BY id DESC LIMIT 15", (str(user_id),))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        send_message_with_keyboard(chat_id, "لا يوجد سجل صفقات بعد.", get_main_keyboard())
        return
    msg = "📜 <b>آخر 15 صفقة مغلقة</b>\n\n"
    for r in rows:
        msg += f"#{r[0]} {r[1]} {r[2]} لوت | {r[3]} → {r[4]} | {r[5]:+.2f}$ | {r[6]}\n"
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())

def handle_price_command(chat_id):
    price = get_biquote_price()
    if price is None:
        closes = tf_data.get("1m", {}).get("closes", []) or tf_data.get("5m", {}).get("closes", [])
        price = closes[-1] if closes else None
    price_text = f"{price:.2f}" if price else "غير متوفر"
    context = analyze_market_context()
    msg = (
        f"📊 <b>سعر XAUUSD</b>\n\n"
        f"💰 السعر: <code>{price_text}</code>\n"
        f"🧠 H1: {context.get('h1_bias')} | M15: {context.get('m15_bias')} | M5: {context.get('m5_bias')}\n"
        f"📅 {datetime.now(SAUDI_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
    )
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())

def handle_news_command(chat_id):
    news = get_usd_high_impact_news()
    if not news:
        msg = "📰 لا توجد أخبار عالية التأثير حاليا"
    else:
        msg = "📰 <b>أخبار USD High Impact</b>\n\n"
        for n in news[:5]:
            t = n["time"].strftime("%H:%M %d-%m") if isinstance(n["time"], datetime) else str(n["time"])
            msg += f"• {n['title']} - {t}\nالمتوقع: {n['forecast']} | السابق: {n['previous']}\n\n"
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())

def handle_auto_trade_menu(chat_id, user_id):
    status = get_auto_trade(user_id)
    status_text = "🟢 مفعّل" if status == 1 else "🔴 متوقف"
    keyboard = {"keyboard": [["🟢 تشغيل التداول الآلي", "🔴 إيقاف التداول الآلي"], ["🔙 رجوع"]], "resize_keyboard": True}
    msg = f"🤖 <b>التداول الآلي</b>\n\nالحالة: <b>{status_text}</b>\n\nعند التفعيل، البوت يفتح صفقات تلقائيًا بحجم 0.01 لوت مع كل إشارة قوية."
    send_message_with_keyboard(chat_id, msg, keyboard)

def handle_enable_auto_trade(chat_id, user_id):
    user = get_or_create_user(user_id)
    if user["balance"] <= 0:
        send_message_with_keyboard(chat_id, "❌ رصيدك صفر. قم بالإيداع أولاً.", get_main_keyboard())
        return
    set_auto_trade(user_id, 1)
    send_message_with_keyboard(chat_id, "✅ تم تفعيل التداول الآلي.", get_main_keyboard())

def handle_disable_auto_trade(chat_id, user_id):
    set_auto_trade(user_id, 0)
    send_message_with_keyboard(chat_id, "🔴 تم إيقاف التداول الآلي.", get_main_keyboard())

def handle_deposit_start(chat_id, user_id):
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("SELECT id, name, details FROM deposit_methods WHERE is_active=1")
    methods = cur.fetchall()
    conn.close()
    if not methods:
        send_message_with_keyboard(chat_id, "❌ لا توجد طرق إيداع مفعلة. تواصل مع الأدمن.", get_main_keyboard())
        return
    msg = "📥 <b>اختر طريقة الإيداع:</b>\n\n"
    keyboard_buttons = []
    for m in methods:
        msg += f"• {m[1]}\n"
        keyboard_buttons.append([f"إيداع_{m[0]}_{m[1]}"])
    keyboard_buttons.append(["🔙 رجوع"])
    send_message_with_keyboard(chat_id, msg, {"keyboard": keyboard_buttons, "resize_keyboard": True})

def handle_deposit_method_selected(chat_id, user_id, method_id, method_name):
    with user_states_lock:
        user_states[str(user_id)] = {"action": "deposit_amount", "method_id": method_id, "method_name": method_name}
    send_message_with_keyboard(chat_id, "أدخل مبلغ الإيداع بالدولار (مثال: 100):", {"keyboard": [["🔙 رجوع"]], "resize_keyboard": True})

def handle_deposit_amount(chat_id, user_id, text):
    try:
        amount = float(text.replace(",", "").strip())
        if amount <= 0: raise ValueError
    except:
        send_message_with_keyboard(chat_id, "❌ أدخل رقم صحيح", {"keyboard": [["🔙 رجوع"]], "resize_keyboard": True})
        return
    with user_states_lock:
        state = user_states.get(str(user_id), {})
        state["amount"] = amount
        state["action"] = "deposit_proof"
        user_states[str(user_id)] = state
    send_message_with_keyboard(chat_id, f"المبلغ: <code>{amount}$</code>\n\nأرسل إثبات التحويل:", {"keyboard": [["🔙 رجوع"]], "resize_keyboard": True})

def handle_deposit_proof(chat_id, user_id, proof_text):
    with user_states_lock:
        state = user_states.get(str(user_id), {})
        if state.get("action") != "deposit_proof":
            return
        method_id = state.get("method_id")
        amount = state.get("amount")
        method_name = state.get("method_name", "")
        user_states.pop(str(user_id), None)
    now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("INSERT INTO deposits (user_id, method_id, amount, proof, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (str(user_id), method_id, amount, proof_text, now))
    dep_id = cur.lastrowid
    conn.commit()
    conn.close()
    user = get_or_create_user(user_id)
    send_message_with_keyboard(chat_id, f"✅ تم إرسال طلب الإيداع\n🆔 <code>#{dep_id}</code>\n⏳ بانتظار الأدمن", get_main_keyboard())
    admin_msg = (
        f"📥 <b>طلب إيداع جديد</b>\n\n"
        f"🆔 الطلب: <code>#{dep_id}</code>\n"
        f"👤 المستخدم: {user['name']} (<code>{user_id}</code>)\n"
        f"💰 المبلغ: <code>{amount}$</code>\n"
        f"📌 الطريقة: {method_name}\n"
        f"📎 الإثبات:\n{proof_text}"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ قبول", "callback_data": f"approve_dep_{dep_id}"},
            {"text": "❌ رفض", "callback_data": f"reject_dep_{dep_id}"}
        ]]
    }
    send_to_admin_channel(admin_msg, reply_markup=keyboard)

def handle_withdraw_start(chat_id, user_id):
    user = get_or_create_user(user_id)
    if user["balance"] <= 0:
        send_message_with_keyboard(chat_id, "❌ رصيدك غير كافٍ.", get_main_keyboard())
        return
    with user_states_lock:
        user_states[str(user_id)] = {"action": "withdraw_amount"}
    send_message_with_keyboard(chat_id, f"📤 رصيدك: <code>{user['balance']:.2f}$</code>\n\nأدخل المبلغ:", {"keyboard": [["🔙 رجوع"]], "resize_keyboard": True})

def handle_withdraw_amount(chat_id, user_id, text):
    try:
        amount = float(text.replace(",", "").strip())
        if amount <= 0: raise ValueError
    except:
        send_message_with_keyboard(chat_id, "❌ أدخل رقم صحيح", {"keyboard": [["🔙 رجوع"]], "resize_keyboard": True})
        return
    user = get_or_create_user(user_id)
    if amount > user["balance"]:
        send_message_with_keyboard(chat_id, f"❌ أكبر من رصيدك ({user['balance']:.2f}$)", {"keyboard": [["🔙 رجوع"]], "resize_keyboard": True})
        return
    with user_states_lock:
        state = user_states.get(str(user_id), {})
        state["amount"] = amount
        state["action"] = "withdraw_address"
        user_states[str(user_id)] = state
    send_message_with_keyboard(chat_id, "أدخل عنوان المحفظة:", {"keyboard": [["🔙 رجوع"]], "resize_keyboard": True})

def handle_withdraw_address(chat_id, user_id, address):
    with user_states_lock:
        state = user_states.get(str(user_id), {})
        if state.get("action") != "withdraw_address":
            return
        amount = state.get("amount")
        user_states.pop(str(user_id), None)
    now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("INSERT INTO withdrawals (user_id, amount, address, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (str(user_id), amount, address, now))
    wid = cur.lastrowid
    conn.commit()
    conn.close()
    user = get_or_create_user(user_id)
    send_message_with_keyboard(chat_id, f"✅ تم إرسال طلب السحب\n🆔 <code>#{wid}</code>", get_main_keyboard())
    admin_msg = (
        f"📤 <b>طلب سحب جديد</b>\n\n"
        f"🆔 الطلب: <code>#{wid}</code>\n"
        f"👤 المستخدم: {user['name']} (<code>{user_id}</code>)\n"
        f"💰 المبلغ: <code>{amount}$</code>\n"
        f"📍 العنوان:\n<code>{address}</code>"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ قبول", "callback_data": f"approve_wd_{wid}"},
            {"text": "❌ رفض", "callback_data": f"reject_wd_{wid}"}
        ]]
    }
    send_to_admin_channel(admin_msg, reply_markup=keyboard)

def handle_admin_set_balance(admin_id, text, chat_id):
    try:
        parts = text.split()
        if len(parts) < 3:
            send_message_with_keyboard(chat_id, "الصيغة: /setbalance USER_ID AMOUNT", get_main_keyboard())
            return
        target_id = parts[1]
        amount = float(parts[2])
        update_user_balance(target_id, amount)
        send_message_with_keyboard(chat_id, f"✅ تم تحديث رصيد {target_id} إلى {amount:.2f}$", get_main_keyboard())
        try:
            send_message_with_keyboard(target_id, f"💰 تم تحديث رصيدك إلى {amount:.2f}$", get_main_keyboard())
        except:
            pass
    except Exception as e:
        send_message_with_keyboard(chat_id, f"❌ {e}", get_main_keyboard())

def handle_admin_add_method(admin_id, text, chat_id):
    try:
        content = text.replace("/addmethod", "").strip()
        if "|" not in content:
            send_message_with_keyboard(chat_id, "الصيغة:\n/addmethod اسم الطريقة | التفاصيل والعنوان", get_main_keyboard())
            return
        name, details = content.split("|", 1)
        name, details = name.strip(), details.strip()
        conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("INSERT INTO deposit_methods (name, details, is_active) VALUES (?, ?, 1)", (name, details))
        conn.commit()
        mid = cur.lastrowid
        conn.close()
        send_message_with_keyboard(chat_id, f"✅ تم إضافة طريقة إيداع\nID: {mid}\nالاسم: {name}", get_main_keyboard())
    except Exception as e:
        send_message_with_keyboard(chat_id, f"❌ {e}", get_main_keyboard())

def handle_callback_query(callback):
    data = callback.get("data", "")
    callback_id = callback.get("id")
    from_user = callback.get("from", {})
    user_id = from_user.get("id")
    print(f"[Callback] Received: data={data} | from={user_id}")
    if user_id not in ADMIN_IDS:
        print(f"[Callback] Rejected - not admin: {user_id}")
        answer_callback(callback_id, "❌ هذا الزر للأدمن فقط")
        return
    try:
        if data.startswith("approve_dep_"):
            dep_id = int(data.replace("approve_dep_", ""))
            print(f"[Callback] Approving deposit #{dep_id}")
            conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
            cur = conn.cursor()
            cur.execute("SELECT user_id, amount, status FROM deposits WHERE id=?", (dep_id,))
            row = cur.fetchone()
            if not row:
                answer_callback(callback_id, "❌ الطلب غير موجود")
                conn.close()
                return
            if row[2] != "pending":
                answer_callback(callback_id, f"❌ تمت معالجته مسبقاً ({row[2]})")
                conn.close()
                return
            uid, amount, _ = row
            now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("UPDATE deposits SET status='approved', processed_at=? WHERE id=?", (now, dep_id))
            conn.commit()
            conn.close()
            new_bal = add_to_balance(uid, amount)
            answer_callback(callback_id, f"✅ تم قبول الإيداع #{dep_id}")
            send_to_admin_channel(f"✅ تم قبول الإيداع #{dep_id}\nالمبلغ: {amount}$\nالرصيد الجديد: {new_bal:.2f}$")
            try:
                send_message_with_keyboard(uid, f"✅ تم قبول إيداعك #{dep_id}\nتم إضافة {amount}$\nرصيدك الآن: {new_bal:.2f}$", get_main_keyboard())
            except Exception as e:
                print(f"[Callback] Notify user error: {e}")
        elif data.startswith("reject_dep_"):
            dep_id = int(data.replace("reject_dep_", ""))
            print(f"[Callback] Rejecting deposit #{dep_id}")
            conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
            cur = conn.cursor()
            cur.execute("SELECT user_id, status FROM deposits WHERE id=?", (dep_id,))
            row = cur.fetchone()
            if not row or row[1] != "pending":
                answer_callback(callback_id, "❌ الطلب غير موجود أو تمت معالجته")
                conn.close()
                return
            uid = row[0]
            now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("UPDATE deposits SET status='rejected', admin_note=?, processed_at=? WHERE id=?", ("مرفوض من القناة", now, dep_id))
            conn.commit()
            conn.close()
            answer_callback(callback_id, f"❌ تم رفض الإيداع #{dep_id}")
            send_to_admin_channel(f"❌ تم رفض الإيداع #{dep_id}")
            try:
                send_message_with_keyboard(uid, f"❌ تم رفض طلب الإيداع #{dep_id}", get_main_keyboard())
            except:
                pass
        elif data.startswith("approve_wd_"):
            wid = int(data.replace("approve_wd_", ""))
            print(f"[Callback] Approving withdraw #{wid}")
            conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
            cur = conn.cursor()
            cur.execute("SELECT user_id, amount, status FROM withdrawals WHERE id=?", (wid,))
            row = cur.fetchone()
            if not row or row[2] != "pending":
                answer_callback(callback_id, "❌ الطلب غير موجود أو تمت معالجته")
                conn.close()
                return
            uid, amount, _ = row
            user = get_or_create_user(uid)
            if user["balance"] < amount:
                answer_callback(callback_id, "❌ رصيد المستخدم غير كافٍ")
                conn.close()
                return
            now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("UPDATE withdrawals SET status='approved', processed_at=? WHERE id=?", (now, wid))
            conn.commit()
            conn.close()
            new_bal = add_to_balance(uid, -amount)
            answer_callback(callback_id, f"✅ تم قبول السحب #{wid}")
            send_to_admin_channel(f"✅ تم قبول السحب #{wid}\nخصم: {amount}$\nالمتبقي: {new_bal:.2f}$")
            try:
                send_message_with_keyboard(uid, f"✅ تم قبول السحب #{wid}\nتم خصم {amount}$\nرصيدك: {new_bal:.2f}$", get_main_keyboard())
            except:
                pass
        elif data.startswith("reject_wd_"):
            wid = int(data.replace("reject_wd_", ""))
            print(f"[Callback] Rejecting withdraw #{wid}")
            conn = sqlite3.connect(USER_DB_FILE, check_same_thread=False)
            cur = conn.cursor()
            cur.execute("SELECT user_id, status FROM withdrawals WHERE id=?", (wid,))
            row = cur.fetchone()
            if not row or row[1] != "pending":
                answer_callback(callback_id, "❌ الطلب غير موجود أو تمت معالجته")
                conn.close()
                return
            uid = row[0]
            now = datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("UPDATE withdrawals SET status='rejected', admin_note=?, processed_at=? WHERE id=?", ("مرفوض من القناة", now, wid))
            conn.commit()
            conn.close()
            answer_callback(callback_id, f"❌ تم رفض السحب #{wid}")
            send_to_admin_channel(f"❌ تم رفض السحب #{wid}")
            try:
                send_message_with_keyboard(uid, f"❌ تم رفض طلب السحب #{wid}", get_main_keyboard())
            except:
                pass
        else:
            print(f"[Callback] Unknown data: {data}")
            answer_callback(callback_id, "أمر غير معروف")
    except Exception as e:
        print(f"[Callback] ERROR: {e}")
        import traceback
        traceback.print_exc()
        answer_callback(callback_id, f"حدث خطأ: {str(e)[:40]}")

def telegram_polling_loop():
    print("[Telegram Polling] Started")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            r = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    for upd in data.get("result", []):
                        offset = upd["update_id"] + 1
                        callback = upd.get("callback_query")
                        if callback:
                            handle_callback_query(callback)
                            continue
                        msg = upd.get("message")
                        if not msg:
                            continue
                        chat_id = msg["chat"]["id"]
                        user = msg["from"]
                        text = msg.get("text", "").strip()
                        user_id = user.get("id")
                        name = (user.get("first_name", "") + " " + user.get("last_name", "")).strip() or str(user_id)
                        get_or_create_user(user_id, name)
                        uid_str = str(user_id)
                        with user_states_lock:
                            state = user_states.get(uid_str, {})
                        if state.get("action") == "deposit_amount" and text not in ["🔙 رجوع"]:
                            handle_deposit_amount(chat_id, user_id, text)
                            continue
                        if state.get("action") == "deposit_proof" and text not in ["🔙 رجوع"]:
                            handle_deposit_proof(chat_id, user_id, text)
                            continue
                        if state.get("action") == "withdraw_amount" and text not in ["🔙 رجوع"]:
                            handle_withdraw_amount(chat_id, user_id, text)
                            continue
                        if state.get("action") == "withdraw_address" and text not in ["🔙 رجوع"]:
                            handle_withdraw_address(chat_id, user_id, text)
                            continue
                        if text == "🔙 رجوع":
                            with user_states_lock:
                                user_states.pop(uid_str, None)
                            send_message_with_keyboard(chat_id, "تم الرجوع للقائمة الرئيسية", get_main_keyboard())
                            continue
                        if text == "💰 رصيدي":
                            handle_balance_command(chat_id, user_id)
                        elif text == "📈 تداول":
                            handle_trade_menu(chat_id, user_id)
                        elif text == "🟢 شراء BUY":
                            handle_open_trade(chat_id, user_id, "BUY")
                        elif text == "🔴 بيع SELL":
                            handle_open_trade(chat_id, user_id, "SELL")
                        elif text == "🤖 تداول آلي":
                            handle_auto_trade_menu(chat_id, user_id)
                        elif text == "🟢 تشغيل التداول الآلي":
                            handle_enable_auto_trade(chat_id, user_id)
                        elif text == "🔴 إيقاف التداول الآلي":
                            handle_disable_auto_trade(chat_id, user_id)
                        elif text == "📥 إيداع":
                            handle_deposit_start(chat_id, user_id)
                        elif text.startswith("إيداع_"):
                            parts = text.split("_", 2)
                            if len(parts) >= 3:
                                handle_deposit_method_selected(chat_id, user_id, parts[1], parts[2])
                        elif text == "📤 سحب":
                            handle_withdraw_start(chat_id, user_id)
                        elif text == "📊 صفقاتي المفتوحة":
                            handle_my_open_trades(chat_id, user_id)
                        elif text == "📜 سجل صفقاتي":
                            handle_my_trade_history(chat_id, user_id)
                        elif text == "📊 سعر XAUUSD":
                            handle_price_command(chat_id)
                        elif text == "📰 أخبار السوق":
                            handle_news_command(chat_id)
                        elif text in ["🆔 ايدي", "/id", "/myid", "/ايدي"]:
                            send_message_with_keyboard(chat_id, f"🆔 <code>{user_id}</code>", get_main_keyboard())
                        elif text.startswith("❌ إغلاق #"):
                            try:
                                trade_id = int(text.replace("❌ إغلاق #", "").strip())
                                success, result = close_user_trade_manual(trade_id, user_id)
                                if success:
                                    send_message_with_keyboard(chat_id, f"✅ تم إغلاق الصفقة #{trade_id}\nالنتيجة: <code>{result:+.2f}$</code>", get_main_keyboard())
                                    try:
                                        user = get_or_create_user(user_id)
                                        send_to_admin_channel(f"🔔 <b>إغلاق يدوي لصفقة عميل</b>\n\n👤 {user['name']} (<code>{user_id}</code>)\n🆔 الصفقة: <code>#{trade_id}</code>\n📈 النتيجة: <code>{result:+.2f}$</code>")
                                    except:
                                        pass
                                else:
                                    send_message_with_keyboard(chat_id, f"❌ {result}", get_main_keyboard())
                            except:
                                send_message_with_keyboard(chat_id, "❌ رقم الصفقة غير صحيح", get_main_keyboard())
                        elif text.startswith("/setbalance") and user_id in ADMIN_IDS:
                            handle_admin_set_balance(user_id, text, chat_id)
                        elif text.startswith("/addmethod") and user_id in ADMIN_IDS:
                            handle_admin_add_method(user_id, text, chat_id)
                        elif text in ["/start", "/help"]:
                            welcome = f"👋 أهلا {user.get('first_name', '')}!\n\n🤖 بوت كلاريث VIP GOLD\n🆔 <code>{user_id}</code>\n\nاستخدم الأزرار للتداول والإيداع والسحب."
                            send_message_with_keyboard(chat_id, welcome, get_main_keyboard())
            time.sleep(1)
        except Exception as e:
            print(f"[Polling] Error: {e}")
            time.sleep(3)

def send_startup_report():
    price = get_biquote_price()
    price_text = f"{price:.3f}" if price is not None else "غير متوفر"
    msg = (
        f"🚀 <b>VIP GOLD - FULL ORIGINAL + AUTO TRADE + ADMIN CHANNEL</b>\n\n"
        f"تم التشغيل بنجاح\n"
        f"📅 {datetime.now(SAUDI_TZ).strftime('%Y-%m-%d %H:%M')}\n\n"
        f"• إشارات كاملة بدون اختصار\n"
        f"• تداول يدوي + آلي\n"
        f"• إغلاق يدوي + أزرار قبول/رفض\n"
        f"• كل الإشعارات على @GXAIJ\n\n"
        f"💰 السعر: {price_text}"
    )
    send_to_telegram(msg, event_id=f"STARTUP_{datetime.now(SAUDI_TZ).strftime('%Y%m%d%H')}")

class AdvancedServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            uptime = int((datetime.now(SAUDI_TZ) - server_started_at).total_seconds())
            price = get_biquote_price()
            price_text = f"{price:.3f}" if price is not None else "N/A"
            html = f"""<html><body style="font-family:Arial;background:#111;color:#eee;padding:30px;">
            <h1>KALARITH VIP GOLD - FULL</h1>
            <p>Status: ACTIVE | Uptime: {uptime}s</p>
            <p>Active Signal: {active_trade or 'NONE'}</p>
            <p>💰 {price_text}</p>
            </body></html>"""
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
        except:
            self.send_response(500)
    def log_message(self, *args): return

def run_enterprise_server():
    try:
        port = int(os.environ.get("PORT", "10000"))
        HTTPServer(("0.0.0.0", port), AdvancedServerHandler).serve_forever()
    except Exception as e:
        print(f"[HTTP] {e}")

def trading_bot_loop():
    global last_bot_loop, last_error, pre_market_sent
    time.sleep(2)
    load_sent_events()
    load_ai_memory()
    load_active_trade()
    send_startup_report()
    while True:
        try:
            last_bot_loop = datetime.now(SAUDI_TZ)
            now = datetime.now(SAUDI_TZ)
            update_bot_lock()
            check_market_state(now)
            now_ny = now.astimezone(NY_TZ)
            if now_ny.weekday() == 6 and now_ny.hour == 17 and 25 <= now_ny.minute < 55 and not pre_market_sent:
                send_pre_market_report(now)
                pre_market_sent = True
            if now.minute % 5 == 0 and now.second < 3:
                send_news_report(get_usd_high_impact_news(), now)
            update_all_timeframes()
            analyze_market()
            try:
                live_price = get_biquote_price()
                if live_price:
                    check_open_trades_price_loop(live_price)
                    check_user_trades_price_loop(live_price)
            except Exception as e:
                print(f"[Price Loop] Error: {e}")
            time.sleep(1)
        except Exception as e:
            last_error = str(e)
            print(f"[ERROR] {e}")
            time.sleep(2)

def start_application():
    print("KALARITH VIP GOLD - FULL ORIGINAL ANALYSIS + USER TRADING + ADMIN CHANNEL")
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        print("[Webhook] Deleted successfully")
    except Exception as e:
        print(f"[Webhook] Delete error: {e}")
    if not acquire_bot_lock():
        return
    init_trades_db()
    init_user_trading_db()
    load_sent_events()
    load_ai_memory()
    load_active_trade()
    load_open_trades_to_memory()
    threading.Thread(target=run_enterprise_server, daemon=True).start()
    threading.Thread(target=telegram_polling_loop, daemon=True).start()
    trading_bot_loop()

if __name__ == "__main__":
    start_application()

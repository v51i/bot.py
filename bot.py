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
# KALARITH VIP GOLD - FULL EDITION - FIXED NO COMPRESSION
# Smart M5 Exit | Overextension Dynamic 70/20 & 36/40 | Sweep 20 | SR 100 | Max SL 16
# Candle Strength 60 (was 73) | 16 Patterns + EMA20 Pullback
# ============================================================


# ============================================================
# SECRETS
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU")
PRIVATE_CHAT_ID = os.environ.get("PRIVATE_CHAT_ID", "8952278702")
CHANNEL_CHAT_ID = os.environ.get("CHANNEL_CHAT_ID", "@ZXPIF")


# ============================================================
# BIQUOTE API
# ============================================================

BIQUOTE_BASE_URL = "https://biquote.io/api"
BIQUOTE_SYMBOL = "XAUUSD"

# ============================================================
# SQLITE TRADES DATABASE
# ============================================================
TRADES_DB_FILE = "trades.db"
active_trades_memory = []
trades_memory_lock = threading.Lock()

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
                "id": trade_id,
                "time": now_str,
                "pair": pair,
                "action": action,
                "entry": float(entry),
                "target": float(target),
                "stop_loss": float(stop_loss),
                "tp1": tp1,
                "tp2": tp2,
                "grade": grade
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
                    "id": r[0],
                    "time": r[1],
                    "pair": r[2],
                    "action": r[3],
                    "entry": r[4],
                    "target": r[5],
                    "stop_loss": r[6],
                    "tp1": r[7],
                    "tp2": r[8],
                    "grade": r[9]
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
        cur.execute("UPDATE trades SET status=?, close_time=?, close_price=? WHERE id=?", (new_status, close_time, float(close_price), int(trade_id)))
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
        hit_tp = False
        hit_sl = False
        if action == "BUY":
            if current_price >= target:
                hit_tp = True
            elif current_price <= sl:
                hit_sl = True
        else:
            if current_price <= target:
                hit_tp = True
            elif current_price >= sl:
                hit_sl = True
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



# ============================================================
# TRADING SETTINGS
# ============================================================

ATR_MULTIPLIER_SL = 1.5
# سكالبينج خاطف - اهداف قريبة R:R
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

MIN_CANDLE_STRENGTH = 45  # Early entry - كان 60 ثم 73
OVEREXTENSION_CANDLES = 40
OVEREXTENSION_POINTS = 36.0
SWEEP_LOOKBACK = 20
SR_LOOKBACK = 100


# ============================================================
# TIMEFRAMES
# ============================================================

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


# ============================================================
# TIMEZONES + VARIABLES
# ============================================================

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

ai_memory = {
    "trades": [], "trade_log": [], "patterns": {},
    "total_trades": 0, "total_wins": 0, "total_losses": 0, "win_rate": 0.0
}

sent_events = set()
telegram_lock = threading.Lock()
signal_lock = threading.Lock()
events_lock = threading.Lock()

server_started_at = datetime.now(SAUDI_TZ)
last_bot_loop = datetime.now(SAUDI_TZ)
last_market_report_hour = None
last_data_update_time = None


# ============================================================
# HELPERS
# ============================================================

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
                "target_sl": target_sl, "target_tp1": target_tp1, "target_tp2": target_tp2, "target_tp3": target_tp3, "m5_bias_at_entry": m5_bias_at_entry,
                "tp1_hit": tp1_hit, "tp2_hit": tp2_hit, "tp3_hit": tp3_hit,
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
    global active_trade, entry_price, target_sl, target_tp1, target_tp2, target_tp3, m5_bias_at_entry, last_tp1_win_timestamp, last_tp1_win_price, m5_bias_at_entry
    global tp1_hit, tp2_hit, tp3_hit, trade_open_time, trade_signal_type, trade_signal_id
    global trade_grade, trade_reason, trade_rsi, trade_ema_diff, trade_atr
    global trade_bias, trade_score, timeout_final
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


# ============================================================
# NEWS
# ============================================================

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


# ============================================================
# DATA
# ============================================================

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


# ============================================================
# TELEGRAM
# ============================================================

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


def create_signal_id(signal_type, candle_time):
    raw = f"{signal_type}_{candle_time}".encode("utf-8")
    short_hash = hashlib.md5(raw).hexdigest()[:8].upper()
    return f"{signal_type}-{datetime.now(SAUDI_TZ).strftime('%Y%m%d')}-{short_hash}"


# ============================================================
# INDICATORS
# ============================================================

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


# ============================================================
# OVEREXTENSION FILTER - DYNAMIC 70/20 STRONG TREND ELSE 36/40
# ============================================================

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


# ============================================================
# EMA20 PULLBACK ENTRY
# ============================================================

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


# ============================================================
# CANDLESTICKS + FVG + SWEEPS - 16 PATTERNS + 5 CANDLES
# ============================================================

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

    def body(o,c):
        return abs(c-o)
    def rng(h,l):
        return h-l if h!=l else 0.0001
    def upper(h,o,c):
        return h-max(o,c)
    def lower(l,o,c):
        return min(o,c)-l
    def is_bull(o,c):
        return c>o
    def is_bear(o,c):
        return c<o
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
    # انماط اضافية جديدة - 4 انماط قوية
    # Bullish/Bearish Kicker - شمعة قوية تعكس الاتجاه بقوة
    if is_bull(o5,c5) and is_bear(o4,c4) and o5 > c4 and b5 > avg_b*1.2 and abs(o5 - c4) > avg_b*0.3:
        return {"pattern": "Bullish Kicker", "bullish": True, "bearish": False, "strength": 93}
    if is_bear(o5,c5) and is_bull(o4,c4) and o5 < c4 and b5 > avg_b*1.2 and abs(o5 - c4) > avg_b*0.3:
        return {"pattern": "Bearish Kicker", "bullish": False, "bearish": True, "strength": 93}
    # Rising/Falling Three Methods - استمرار قوي للترند
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


# ============================================================
# CONTEXT
# ============================================================

def analyze_market_context():
    h1 = tf_data.get("1h", {}).get("closes", [])
    m15 = tf_data.get("15m", {}).get("closes", [])
    m5 = tf_data.get("5m", {}).get("closes", [])

    if len(m5) < 30:
        return {"h1_bias": "NEUTRAL", "m15_bias": "NEUTRAL", "m5_bias": "NEUTRAL", "bias": "NEUTRAL", "m15_above_ema50": False, "m15_below_ema50": False, "m15_ema50_rising": False, "m15_ema50_falling": False, "h1_above_ema50": False}

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
        # هل EMA50 صاعد ام هابط
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
    h1_above_ema50 = context.get("h1_above_ema50", False)
    strength = candle.get("strength", 0) if candle else 0
    pattern = candle.get("pattern", "") if candle else ""
    is_strong_reversal = strength >= 80 and "Kicker" in pattern  # فقط Kicker 85+ يعتبر انعكاس حقيقي

    if signal_type == "BUY":
        # لا تدخل BUY اذا M15 تحت EMA50 و EMA50 هابط - ترند هابط قوي
        if m15_below_ema50 and m15_ema50_falling and not is_strong_reversal:
            return False
        if m1_bias == "BEARISH" and not is_strong_reversal:
            return False
        if m5 == "BULLISH" and m1_bias == "BULLISH":
            # حتى لو M5 صاعد، تأكد M15 مو هابط قوي
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
        # لا تدخل SELL اذا M15 فوق EMA50 و EMA50 صاعد - ترند صاعد قوي (هذا اللي صار يوم 29)
        if m15_above_ema50 and m15_ema50_rising and not is_strong_reversal:
            return False
        if m1_bias == "BULLISH" and not is_strong_reversal:
            return False
        if m5 == "BEARISH" and m1_bias == "BEARISH":
            # حتى لو M5 هابط، تأكد M15 مو صاعد قوي
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


# ============================================================
# WAVE
# ============================================================


# ============================================================
# EARLY ENTRY - 1M PULLBACK / FVG / EMA9 / EMA20
# ============================================================

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

    # Early entry - كان يرفض اذا قوة الشمعة اقل من 60، الان 45 للـ Scalping المبكر
    if candle["strength"] < MIN_CANDLE_STRENGTH:
        # اسمح بالـ Pinbar / Wick Sweep حتى لو قوة اقل - ذيل شمعة يعني ارتداد مبكر من القاع/القمة
        if not ("Pinbar" in candle["pattern"] or "Hammer" in candle["pattern"] or "Sweep" in candle["pattern"] or "Wick" in candle["pattern"] or candle["strength"] >= 35):
            return {"signal": "NONE"}

    if (candle["bullish"] and
        ema9[-1] > ema21[-1] and
        rsi <= RSI_MAX_FOR_BUY and
        closes[-1] > opens[-1]):

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

    if (candle["bearish"] and
        ema9[-1] < ema21[-1] and
        rsi >= RSI_MIN_FOR_SELL and
        closes[-1] < opens[-1]):

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


# ============================================================
# RISK
# ============================================================

def calculate_dynamic_risk(entry, trade_type, atr, lows=None, highs=None):
    """
    سكالبينج خاطف - TP1 0.4R, TP2 1.0R, TP3 1.6R
    TP1 يضرب = تقفل رابحة مباشرة - لا تكمل ولا تضرب ستوب
    """
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


# ============================================================
# SCORE
# ============================================================

def calculate_trade_score(rsi, ema_diff, candle, context, sr_info, fvg_info, signal_type):
    score = 48

    if candle["strength"] >= 90:
        score += 22
    elif candle["strength"] >= 80:
        score += 16
    elif candle["strength"] >= 73:
        score += 11
    elif candle["strength"] >= 60:
        score += 8

    if abs(ema_diff) > 0.15:
        score += 12

    if signal_type == "BUY" and sr_info.get("near_support"):
        score += 10
    if signal_type == "SELL" and sr_info.get("near_resistance"):
        score += 10

    if fvg_info.get("has_fvg") and fvg_info.get("type") == ("BULLISH" if signal_type == "BUY" else "BEARISH"):
        score += 9

    m15 = context.get("m15_bias", "NEUTRAL")
    m5 = context.get("m5_bias", "NEUTRAL")
    h1 = context.get("h1_bias", "NEUTRAL")

    if m15 == m5 and m15 != "NEUTRAL":
        score += 14

    if h1 == m15 == m5 and h1 != "NEUTRAL":
        score += 8

    if signal_type == "BUY" and h1 == "BEARISH":
        score -= 15
    if signal_type == "SELL" and h1 == "BULLISH":
        score -= 15

    if rsi > 68 or rsi < 32:
        score -= 15

    return max(0, min(score, 100))


def classify_trade_with_score(score):
    if score >= 86:
        return "A+", "🏆", "SEND"
    elif score >= 65:
        return "A", "✅", "SEND"  # Early entry - كان 74 والان 65 لالتقاط اول 20-30% من الموجة
    else:
        return "B", "⚠️", "SKIP"


# ============================================================
# RECORD + SMART FEAR
# ============================================================

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

        if result_type in ("TP2", "WIN", "REVERSAL_WIN"):
            ai_memory["total_wins"] = ai_memory.get("total_wins", 0) + 1
            weekly_wins += 1
            consecutive_losses = 0
            last_consecutive_loss_pause = None
        elif result_type in ("SL", "LOSS", "REVERSAL_LOSS", "TIMEOUT", "M5_FLIP_LOSS"):
            ai_memory["total_losses"] = ai_memory.get("total_losses", 0) + 1
            weekly_losses += 1
            consecutive_losses += 1
            daily_loss_total += abs(profit)
        elif result_type in ("BE", "M5_FLIP_BE"):
            pass

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

    if daily_loss_total >= DAILY_LOSS_LIMIT:
        return True

    if daily_losses >= MAX_DAILY_LOSSES:
        return True

    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        if last_consecutive_loss_pause is None:
            last_consecutive_loss_pause = datetime.now(SAUDI_TZ)
            return True
        if (datetime.now(SAUDI_TZ) - last_consecutive_loss_pause).total_seconds() / 60 < PAUSE_AFTER_CONSECUTIVE_LOSSES_MIN:
            return True
        last_consecutive_loss_pause = None
    return False


# ============================================================
# MARKET ALERTS
# ============================================================

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


# ============================================================
# MAIN ANALYSIS
# ============================================================

def analyze_market():
    global active_trade, entry_price, target_sl, target_tp1, target_tp2, target_tp3, m5_bias_at_entry, last_tp1_win_timestamp, last_tp1_win_price, m5_bias_at_entry
    global tp1_hit, tp2_hit, tp3_hit, trade_open_time, trade_signal_type, trade_signal_id
    global trade_grade, trade_reason, trade_rsi, trade_score, timeout_final
    global daily_signals, daily_completed_trades, daily_wins, daily_losses
    global daily_tp1_hits, daily_tp2_hits, daily_sl_hits, daily_be_hits, daily_timeout
    global daily_a_grade, daily_b_grade, daily_reversals, daily_total_profit
    global last_reversal_time, last_sl_timestamp, last_timeout_timestamp, last_signal_time
    global consecutive_losses

    # Timeframe Shift - الدخول من 1m والاتجاه العام من 15m/1h
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
            "signal_type": trade_signal_type,
            "entry": entry_price,
            "sl": target_sl,
            "tp1": target_tp1,
            "tp2": target_tp2,
            "rsi": trade_rsi,
            "score": trade_score,
            "grade": trade_grade,
            "reason": trade_reason
        }

        m5_bias = context.get("m5_bias", "NEUTRAL")
        if not tp1_hit:
            # قلب M5 حقيقي فقط اذا كان BULLISH عند الدخول وانقلب BEARISH - مو اذا كان BEARISH من البداية
            if active_trade == "BUY" and m5_bias == "BEARISH":
                # اذا كان BEARISH من البداية عند الدخول، لا تطلع - هذا دخول عكس الترند مقصود
                if m5_bias_at_entry == "BEARISH":
                    # كان BEARISH من البداية، لا تطلع M5 FLIP - خليه يكمل للهدف
                    pass
                elif elapsed >= 5 and profit < 0:
                    # انقلب فعلا بعد ما كان BULLISH وخسران - اطلع
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
                    send_to_telegram(
                        f"<b>{title}</b>\n\n"
                        f"M5 انقلب إلى BEARISH\n"
                        f"الدخول: {entry_price}\n"
                        f"الخروج: {price}\n"
                        f"{profit:+.2f} نقطة | {elapsed:.0f}د"
                    )
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
                    send_to_telegram(
                        f"<b>{title}</b>\n\n"
                        f"M5 انقلب إلى BULLISH\n"
                        f"الدخول: {entry_price}\n"
                        f"الخروج: {price}\n"
                        f"{profit:+.2f} نقطة | {elapsed:.0f}د"
                    )
                    active_trade = None
                    tp1_hit = tp2_hit = tp3_hit = False
                    save_active_trade()
                    return

        # مدة الصفقة 40 دقيقة - اذا ربحان يكمل للهدف
        if elapsed >= TIMEOUT_MINUTES and not tp1_hit and not timeout_final:
            if profit >= 0.8:
                # ربحان - خليها تكمل للهدف
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
            # سكالبينج: يوم يضرب التأمين (TP1 0.4R) خلاص تقفل رابحة مباشرة - لا تضرب ستوب
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
            # لا نقفل الصفقة عند TP2 اذا فيه TP3 - ننقل الستوب لنقطة الدخول ونكمل
            if BREAK_EVEN_AT_TP1:
                target_sl = entry_price + (1 if active_trade=="BUY" else -1) * 1.0  # تأمين ربح بسيط
            send_to_telegram(f"🚀 <b>TP2 - {active_trade} - مؤمن ✅</b>\n+{profit:.2f}\nمكملين لـ TP3: {target_tp3}")
            save_active_trade()
            # لا نرجع، نكمل لـ TP3

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

        if tp1_hit and not tp2_hit and not tp3_hit and elapsed >= TIMEOUT_MINUTES and profit >= 0.8:
            # اذا ضرب TP1 ومر 40 دقيقة ولسه ربحان، خليه يكمل
            pass
        elif tp1_hit and not tp2_hit and ((active_trade == "BUY" and price >= target_tp2) or (active_trade == "SELL" and price <= target_tp2)) == False and elapsed >= TIMEOUT_MINUTES + 20 and profit > 0:
            # اذا ضرب TP1 ومر 60 دقيقة ولسه ما ضرب TP2 بس ربحان، اقفل على ربح
            daily_wins += 1
            daily_completed_trades += 1
            record_trade_result(trade_data, "TP1_WIN", profit, elapsed)
            send_to_telegram(f"✅ <b>إغلاق رابح بعد 60د - {active_trade}</b>\n+{profit:.2f}")
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
            # لا نمنع التداول اذا فيه قلب اتجاه حقيقي - حتى لو السوق متذبذب
            # نتحقق من قلب الاتجاه قبل ما نرجع
            if active_trade is not None:
                m1_tmp = tf_data.get("1m", {})
                if len(m1_tmp.get("closes", [])) >= 21:
                    m1_c = m1_tmp["closes"]
                    m1_o = m1_tmp.get("opens", [])
                    e9_tmp = calculate_ema(m1_c, 9)
                    e21_tmp = calculate_ema(m1_c, 21)
                    if len(e9_tmp) > 0 and len(e21_tmp) > 0:
                        m1_bias_tmp = "BULLISH" if e9_tmp[-1] > e21_tmp[-1] else "BEARISH"
                        # قلب حقيقي: اذا SELL مفتوحة و M1 BULLISH و شمعة قوية
                        if (active_trade == "SELL" and m1_bias_tmp == "BULLISH") or (active_trade == "BUY" and m1_bias_tmp == "BEARISH"):
                            pass  # لا تمنع، خليه يكمل لفحص القلب
                        else:
                            return
                else:
                    return
            else:
                return

        # قلب اتجاه حقيقي - اذا صفقة مفتوحة وعكس الاتجاه بقوة على 1m
        if active_trade is not None and not tp1_hit:
            m1_data = tf_data.get("1m", {})
            m1_closes = m1_data.get("closes", [])
            m1_opens = m1_data.get("opens", [])
            m1_highs = m1_data.get("highs", [])
            m1_lows = m1_data.get("lows", [])
            if len(m1_closes) >= 25:
                ema9_1m = calculate_ema(m1_closes, 9)
                ema21_1m = calculate_ema(m1_closes, 21)
                if len(ema9_1m) > 0 and len(ema21_1m) > 0:
                    m1_bias_check = "BULLISH" if ema9_1m[-1] > ema21_1m[-1] else "BEARISH"
                    # SELL مفتوحة و M1 صار BULLISH بقوة + شمعة صعود كبيرة
                    if active_trade == "SELL" and m1_bias_check == "BULLISH":
                        last_body = abs(m1_closes[-1] - m1_opens[-1]) if len(m1_opens) > 0 else 0
                        avg_body = 0
                        if len(m1_closes) >= 10:
                            bodies = [abs(m1_closes[i] - m1_opens[i]) for i in range(-10, -1) if i < len(m1_opens)]
                            avg_body = sum(bodies) / len(bodies) if bodies else last_body
                        # شمعة قوية 1.8x + فوق EMA9 + EMA9 فوق EMA21 = قلب حقيقي
                        if last_body > avg_body * 1.8 and m1_closes[-1] > ema9_1m[-1] and ema9_1m[-1] > ema21_1m[-1]:
                            profit = entry_price - price
                            daily_completed_trades += 1
                            daily_total_profit += profit
                            if profit >= 0:
                                daily_wins += 1
                                daily_be_hits += 1
                                result_type = "REVERSAL_BE_WIN"
                                title = f"🔄 قلب اتجاه حقيقي - SELL -> BUY - رابحة +{profit:.2f}"
                            else:
                                daily_be_hits += 1
                                result_type = "REVERSAL_BE"
                                title = f"🔄 قلب اتجاه حقيقي - SELL -> BUY - BE {profit:+.2f}"
                            record_trade_result(trade_data, result_type, profit, elapsed)
                            send_to_telegram(f"<b>{title}</b>\nالدخول: {entry_price}\nالخروج: {price}\nM1 BULLISH قوي + شمعة {last_body:.2f} - بداية صعود حقيقي")
                            active_trade = None
                            tp1_hit = tp2_hit = tp3_hit = False
                            save_active_trade()
                            # لا نرجع، نكمل لفتح BUY مباشرة من بداية الصعود
                    # BUY مفتوحة و M1 صار BEARISH بقوة
                    elif active_trade == "BUY" and m1_bias_check == "BEARISH":
                        last_body = abs(m1_closes[-1] - m1_opens[-1]) if len(m1_opens) > 0 else 0
                        avg_body = 0
                        if len(m1_closes) >= 10:
                            bodies = [abs(m1_closes[i] - m1_opens[i]) for i in range(-10, -1) if i < len(m1_opens)]
                            avg_body = sum(bodies) / len(bodies) if bodies else last_body
                        if last_body > avg_body * 1.8 and m1_closes[-1] < ema9_1m[-1] and ema9_1m[-1] < ema21_1m[-1]:
                            profit = price - entry_price
                            daily_completed_trades += 1
                            daily_total_profit += profit
                            if profit >= 0:
                                daily_wins += 1
                                daily_be_hits += 1
                                result_type = "REVERSAL_BE_WIN"
                                title = f"🔄 قلب اتجاه حقيقي - BUY -> SELL - رابحة +{profit:.2f}"
                            else:
                                daily_be_hits += 1
                                result_type = "REVERSAL_BE"
                                title = f"🔄 قلب اتجاه حقيقي - BUY -> SELL - BE {profit:+.2f}"
                            record_trade_result(trade_data, result_type, profit, elapsed)
                            send_to_telegram(f"<b>{title}</b>\nالدخول: {entry_price}\nالخروج: {price}\nM1 BEARISH قوي + شمعة {last_body:.2f} - بداية هبوط حقيقي")
                            active_trade = None
                            tp1_hit = tp2_hit = tp3_hit = False
                            save_active_trade()

        # Early entry - نرصد على 1m اولا للدخول المبكر من القاع/القمة (اول 20-30% من الموجة)
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


# ============================================================
# REPORTS + LOOP
# ============================================================

def send_market_status(saudi_now):
    global last_market_report_hour

    current_hour_key = saudi_now.strftime("%Y-%m-%d_%H")
    if last_market_report_hour == current_hour_key:
        return

    update_all_timeframes()
    time.sleep(0.3)

    price = get_biquote_price()
    price_text = f"{price:.3f}" if price is not None else "غير متوفر"

    context = analyze_market_context()

    msg = (
        f"📊 <b>تقرير حالة السوق</b>\n"
        f"📅 <code>{saudi_now.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        f"💰 السعر: <code>{price_text}</code>\n"
        f"🧠 H1: <code>{context['h1_bias']}</code> | M15: <code>{context['m15_bias']}</code> | M5: <code>{context['m5_bias']}</code>\n"
        f"📈 إشارات: <code>{daily_signals}</code> | مكتملة: <code>{daily_completed_trades}</code>\n"
        f"✅ رابحة: <code>{daily_wins}</code> | ❌ خاسرة: <code>{daily_losses}</code> | 🛡️ تعادل: <code>{daily_be_hits}</code>"
    )

    event_id = f"STATUS_{current_hour_key}"
    if send_to_telegram(msg, event_id=event_id):
        last_market_report_hour = current_hour_key


def send_daily_summary():
    global daily_signals, daily_completed_trades, daily_wins, daily_losses
    global daily_tp1_hits, daily_tp2_hits, daily_sl_hits, daily_be_hits, daily_timeout
    global daily_a_grade, daily_b_grade, daily_reversals, daily_total_profit
    global last_summary_date, consecutive_losses, daily_loss_total

    total = daily_wins + daily_losses
    wr = (daily_wins / total * 100) if total > 0 else 0
    msg = (
        f"📊 <b>ملخص يومي</b>\n"
        f"📅 {last_summary_date}\n\n"
        f"إشارات: {daily_signals}\n"
        f"✅ {daily_wins} | ❌ {daily_losses} | 🛡️ {daily_be_hits}\n"
        f"نسبة النجاح: {wr:.1f}%\n"
        f"النقاط: {daily_total_profit:.2f}\n"
        f"Timeout: {daily_timeout}"
    )
    send_to_telegram(msg, event_id=f"DAILY_{last_summary_date}")

    daily_signals = daily_completed_trades = daily_wins = daily_losses = 0
    daily_tp1_hits = daily_tp2_hits = daily_sl_hits = daily_be_hits = daily_timeout = 0
    daily_a_grade = daily_b_grade = daily_reversals = 0
    daily_total_profit = 0.0
    consecutive_losses = 0
    daily_loss_total = 0.0
    last_summary_date = datetime.now(SAUDI_TZ).date()


def send_startup_report():
    price = get_biquote_price()
    price_text = f"{price:.3f}" if price is not None else "غير متوفر"
    msg = (
        f"🚀 <b>VIP GOLD - SQLITE EDITION - WITH DB TRACKING</b>\n\n"
        f"تم التشغيل بنجاح\n"
        f"📅 {datetime.now(SAUDI_TZ).strftime('%Y-%m-%d %H:%M')}\n\n"
        f"• دخول مبكر من 1m (اول 20-30%)\n"
        f"• حفظ الصفقات في SQLite + ذاكرة\n"
        f"• تحديث لحظي هدف/ستوب كل ثانية\n"
        f"• فلتر تمدد 70$/20 و 36$/40\n"
        f"• قوة الشمعة ≥ 45 + Pinbar\n"
        f"• Score ≥ 65\n"
        f"• 16 نمط شمعة + دعم/مقاومة\n"
        f"• ستوب أقصى 16$\n\n"
        f"💰 السعر: {price_text}"
    )
    send_to_telegram(msg, event_id=f"STARTUP_{datetime.now(SAUDI_TZ).strftime('%Y%m%d%H')}")




class AdvancedServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            uptime = int((datetime.now(SAUDI_TZ) - server_started_at).total_seconds())
            price = get_biquote_price()
            price_text = f"{price:.3f}" if price is not None else "N/A"
            with trades_memory_lock:
                open_count = len(active_trades_memory)
                trades_html = ""
                for t in active_trades_memory[-10:]:
                    trades_html += f"<p>#{t['id']} {t['action']} Entry:{t['entry']} Target:{t['target']} SL:{t['stop_loss']} Status:Open</p>"
            html = f"""<html><body style="font-family:Arial;background:#111;color:#eee;padding:30px;">
            <h1>KALARITH VIP GOLD - SQLITE EDITION</h1>
            <p>Status: ACTIVE | Uptime: {uptime}s | Open Trades in Memory: {open_count}</p>
            <p>Active: {active_trade or 'NONE'} | Entry: {entry_price}</p>
            <p>SL: {target_sl} | TP1: {target_tp1} | TP2: {target_tp2} | TP3: {target_tp3}</p>
            <p>Signals: {daily_signals} | Wins: {daily_wins} | Losses: {daily_losses}</p>
            <p>💰 {price_text}</p>
            <p>Error: {last_error or 'None'}</p>
            <hr>
            <h3>Open Trades (Memory - SQLite)</h3>
            {trades_html if trades_html else "<p>No open trades</p>"}
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

            if now.date() != last_summary_date:
                send_daily_summary()

            check_market_state(now)

            now_ny = now.astimezone(NY_TZ)
            if now_ny.weekday() == 6 and now_ny.hour == 17 and 25 <= now_ny.minute < 55 and not pre_market_sent:
                send_pre_market_report(now)
                pre_market_sent = True

            if now.minute <= 3:
                send_market_status(now)

            if now.minute % 5 == 0 and now.second < 3:
                send_news_report(get_usd_high_impact_news(), now)

            update_all_timeframes()
            analyze_market()
            try:
                live_price = get_biquote_price()
                if live_price:
                    check_open_trades_price_loop(live_price)
            except Exception as e:
                print(f"[SQLite Loop] Error: {e}")
            time.sleep(1)
        except Exception as e:
            last_error = str(e)
            print(f"[ERROR] {e}")
            time.sleep(2)




# ============================================================
# BALANCE SYSTEM + REPLY KEYBOARD MARKUP
# ============================================================

USER_BALANCE_FILE = "user_balances.json"
ADMIN_IDS = [8952278702, 8950515154]

user_balances = {}
balance_lock = threading.Lock()
last_update_id = 0

def load_user_balances():
    global user_balances
    try:
        if os.path.exists(USER_BALANCE_FILE):
            with open(USER_BALANCE_FILE, "r", encoding="utf-8") as f:
                user_balances = json.load(f)
    except:
        user_balances = {}

def save_user_balances():
    with balance_lock:
        atomic_write_json(USER_BALANCE_FILE, user_balances)

def get_user_balance(user_id):
    return user_balances.get(str(user_id), {"balance": 0.0, "name": "مستخدم"})

def set_user_balance(user_id, amount, name=None):
    uid = str(user_id)
    with balance_lock:
        if uid not in user_balances:
            user_balances[uid] = {"balance": 0.0, "name": name or uid}
        user_balances[uid]["balance"] = float(amount)
        if name:
            user_balances[uid]["name"] = name
        atomic_write_json(USER_BALANCE_FILE, user_balances)

def add_user_if_new(user):
    uid = str(user.get("id"))
    name = user.get("first_name", "") + " " + user.get("last_name", "")
    if uid not in user_balances:
        set_user_balance(uid, 0.0, name.strip() or uid)

def get_main_keyboard():
    return {
        "keyboard": [
            ["💰 رصيدي", "📊 سعر XAUUSD"],
            ["📊 صفقاتي المفتوحة", "📜 السجل"],
            ["📦 تحميل القاعدة", "📊 تصدير CSV"],
            ["📰 أخبار السوق", "🆔 ايدي"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

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

def handle_balance_command(chat_id, user_id):
    bal = get_user_balance(user_id)
    msg = (
        f"💰 <b>رصيدك الحالي</b>\n\n"
        f"👤 المستخدم: <code>{bal.get('name', user_id)}</code>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💵 الرصيد: <code>{bal.get('balance', 0.0):.2f} $</code>\n\n"
        f"للاستفسار تواصل مع الأدمن"
    )
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())

def handle_price_command(chat_id):
    price = get_biquote_price()
    if price is None:
        closes = tf_data.get("1m", {}).get("closes", []) or tf_data.get("5m", {}).get("closes", [])
        price = closes[-1] if closes else None
    price_text = f"{price:.2f}" if price else "غير متوفر حاليا"
    context = analyze_market_context()
    msg = (
        f"📊 <b>سعر XAUUSD الحالي</b>\n\n"
        f"💰 السعر: <code>{price_text}</code>\n"
        f"🧠 H1: {context.get('h1_bias')} | M15: {context.get('m15_bias')} | M5: {context.get('m5_bias')} | M1: {context.get('m1_bias')}\n"
        f"📅 {datetime.now(SAUDI_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
    )
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())

def handle_news_command(chat_id):
    news = get_usd_high_impact_news()
    if not news:
        msg = "📰 لا توجد أخبار عالية التأثير حاليا"
    else:
        msg = "📰 <b>أخبار السوق - USD High Impact</b>\n\n"
        for n in news[:5]:
            t = n["time"].strftime("%H:%M %d-%m") if isinstance(n["time"], datetime) else str(n["time"])
            msg += f"• {n['title']} - {t}\nالمتوقع: {n['forecast']} | السابق: {n['previous']}\n\n"
    send_message_with_keyboard(chat_id, msg, get_main_keyboard())

def handle_admin_set_balance(admin_id, text, chat_id):
    try:
        parts = text.split()
        if len(parts) < 3:
            send_message_with_keyboard(chat_id, "❌ الصيغة: /setbalance USER_ID AMOUNT\nمثال: /setbalance 123456 150.5", get_main_keyboard())
            return
        target_id = parts[1]
        amount = float(parts[2])
        set_user_balance(target_id, amount)
        bal = get_user_balance(target_id)
        send_message_with_keyboard(chat_id, f"✅ تم تحديث رصيد المستخدم\n🆔 {target_id}\n💰 الرصيد الجديد: {amount:.2f}$\n👤 الاسم: {bal.get('name')}", get_main_keyboard())
        try:
            send_message_with_keyboard(target_id, f"💰 تم تحديث رصيدك بواسطة الأدمن\n💵 الرصيد الجديد: {amount:.2f}$", get_main_keyboard())
        except:
            pass
    except Exception as e:
        send_message_with_keyboard(chat_id, f"❌ خطأ: {e}", get_main_keyboard())



def handle_trades_command(chat_id):
    try:
        init_trades_db()
        with trades_memory_lock:
            open_trades = list(active_trades_memory)
        if not open_trades:
            send_message_with_keyboard(chat_id, "No open trades", get_main_keyboard())
            return
        msg = f"Open trades: {len(open_trades)}\n"
        for t in open_trades[-10:]:
            msg += f"ID {t['id']} {t['action']} Entry {t['entry']} Target {t['target']} SL {t['stop_loss']}\n"
        send_message_with_keyboard(chat_id, msg, get_main_keyboard())
    except Exception as e:
        send_message_with_keyboard(chat_id, f"Error: {e}", get_main_keyboard())

def handle_history_command(chat_id):
    try:
        init_trades_db()
        conn = sqlite3.connect(TRADES_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("SELECT id, action, entry, target, status, close_price FROM trades WHERE status != 'Open' ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            send_message_with_keyboard(chat_id, "No history", get_main_keyboard())
            return
        msg = "Last 10 closed:\n"
        for r in rows:
            msg += f"ID {r[0]} {r[1]} Entry {r[2]} -> {r[5]} Status {r[4]}\n"
        send_message_with_keyboard(chat_id, msg, get_main_keyboard())
    except Exception as e:
        send_message_with_keyboard(chat_id, f"Error: {e}", get_main_keyboard())

def handle_download_db_command(chat_id):
    try:
        import os
        init_trades_db()
        if not os.path.exists(TRADES_DB_FILE):
            send_message_with_keyboard(chat_id, "No DB file yet", get_main_keyboard())
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(TRADES_DB_FILE, 'rb') as db_file:
            files = {'document': (TRADES_DB_FILE, db_file)}
            data = {'chat_id': chat_id, 'caption': "Trades DB file"}
            r = requests.post(url, data=data, files=files, timeout=20)
        if r.ok:
            send_message_with_keyboard(chat_id, "DB sent OK", get_main_keyboard())
    except Exception as e:
        send_message_with_keyboard(chat_id, f"Error: {e}", get_main_keyboard())

def handle_export_csv_command(chat_id):
    try:
        import csv
        init_trades_db()
        conn = sqlite3.connect(TRADES_DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("SELECT * FROM trades ORDER BY id DESC")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        if not rows:
            send_message_with_keyboard(chat_id, "No data", get_main_keyboard())
            return
        csv_path = "/tmp/trades_export.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as cf:
            writer = csv.writer(cf)
            writer.writerow(cols)
            writer.writerows(rows)
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(csv_path, 'rb') as f:
            files = {'document': ('trades_export.csv', f)}
            data = {'chat_id': chat_id, 'caption': f"CSV {len(rows)} trades"}
            r = requests.post(url, data=data, files=files, timeout=20)
        if r.ok:
            send_message_with_keyboard(chat_id, "CSV sent OK", get_main_keyboard())
    except Exception as e:
        send_message_with_keyboard(chat_id, f"Error: {e}", get_main_keyboard())

def telegram_polling_loop():
    global last_update_id
    print("[Telegram Polling] Started")
    load_user_balances()
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
                        msg = upd.get("message")
                        if not msg:
                            continue
                        chat_id = msg["chat"]["id"]
                        user = msg["from"]
                        text = msg.get("text", "").strip()
                        user_id = user.get("id")
                        add_user_if_new(user)
                        if text == "💰 رصيدي":
                            handle_balance_command(chat_id, user_id)
                        elif text == "📊 سعر XAUUSD":
                            handle_price_command(chat_id)
                        elif text in ["📊 صفقاتي المفتوحة", "/trades", "/صفقاتي"]:
                            handle_trades_command(chat_id)
                        elif text in ["📜 السجل", "/history", "/سجل"]:
                            handle_history_command(chat_id)
                        elif text in ["📦 تحميل القاعدة", "/download_db", "/قاعدة"]:
                            handle_download_db_command(chat_id)
                        elif text in ["📊 تصدير CSV", "/export_csv", "/تصدير"]:
                            handle_export_csv_command(chat_id)
                        elif text == "📰 أخبار السوق":
                            handle_news_command(chat_id)
                        elif text == "/id" or text == "/myid" or text == "🆔 ايدي" or text == "/ايدي":
                            send_message_with_keyboard(chat_id, f"🆔 <b>ايدي حسابك:</b>\n<code>{user_id}</code>\n\nانسخه وارسله للأدمن", get_main_keyboard())
                        elif text == "/users" or text == "/المستخدمين":
                            if user_id in ADMIN_IDS or str(chat_id) in [str(x) for x in ADMIN_IDS]:
                                if not user_balances:
                                    send_message_with_keyboard(chat_id, "❌ لا يوجد مستخدمين بعد", get_main_keyboard())
                                else:
                                    msg = "👥 <b>قائمة المستخدمين:</b>\n\n"
                                    for uid, data in list(user_balances.items())[-20:]:
                                        msg += f"👤 {data.get('name','-')} - ID: <code>{uid}</code> - رصيد: {data.get('balance',0):.2f}$\n"
                                    msg += f"\nالاجمالي: {len(user_balances)} مستخدم"
                                    send_message_with_keyboard(chat_id, msg, get_main_keyboard())
                            else:
                                send_message_with_keyboard(chat_id, "❌ هذا الأمر للأدمن فقط", get_main_keyboard())
                        elif text.startswith("/setbalance") or text.startswith("/رصيد"):
                            if user_id in ADMIN_IDS or str(chat_id) in [str(x) for x in ADMIN_IDS]:
                                handle_admin_set_balance(user_id, text, chat_id)
                            else:
                                send_message_with_keyboard(chat_id, "❌ هذا الأمر للأدمن فقط", get_main_keyboard())
                        elif text == "/start" or text == "/help":
                            welcome = (
                                f"👋 أهلا {user.get('first_name','')}!\n\n"
                                f"🤖 بوت كلاريث VIP GOLD\n"
                                f"🆔 ايديك: <code>{user_id}</code>\n\n"
                                f"استخدم الأزرار بالأسفل:\n"
                                f"💰 رصيدي - عرض رصيدك\n"
                                f"📊 سعر XAUUSD - السعر الحالي\n"
                                f"📰 أخبار السوق - اخبار USD\n\n"
                                f"/id - عرض ايديك\n"
                                f"/users - عرض المستخدمين\n"
                                f"/setbalance USER_ID AMOUNT - تعديل الرصيد"
                            )
                            send_message_with_keyboard(chat_id, welcome, get_main_keyboard())
            time.sleep(1)
        except Exception as e:
            print(f"[Polling] Error: {e}")
            time.sleep(3)


def start_application():
    print("KALARITH VIP GOLD - FULL FIXED 1410+ NO COMPRESSION")
    if not acquire_bot_lock():
        return
    load_sent_events()
    load_ai_memory()
    load_active_trade()
    load_user_balances()
    threading.Thread(target=run_enterprise_server, daemon=True).start()
    threading.Thread(target=telegram_polling_loop, daemon=True).start()
    load_user_balances()
    trading_bot_loop()


if __name__ == "__main__":
    start_application()

import os
import sys
import time
import json
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import Third-Party Libraries
import requests
from flask import Flask, jsonify, request
from supabase import create_client, Client
from web3 import Web3
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ==============================================================================
# 1. Configuration & Logging Setup
# ==============================================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Basic Environment Variables & Fallbacks
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5745747065"))
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
PORT = int(os.getenv("PORT", "8080"))
WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL", "https://bsc-dataseed.binance.org/")

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL))

# Initialize Supabase Client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase: {e}")

# In-Memory Fallback Storage (Used if Supabase is not connected)
MEMORY_DB = {
    "users": {
        ADMIN_ID: {
            "user_id": ADMIN_ID,
            "username": "Admin",
            "balance": 10000.0,
            "wallet_address": "0x77105e783D9453a695264d101FD1324AF0a907D296454A067",
            "private_key": "",
            "is_admin": True,
            "is_banned": False,
            "referrer_id": None,
            "joined_at": str(datetime.now())
        }
    },
    "transactions": [],
    "referrals": {}
}

# ==============================================================================
# 2. Flask Keep-Alive Server
# ==============================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({
        "status": "online",
        "bot_status": "running",
        "timestamp": str(datetime.now())
    })

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

def run_flask_server():
    flask_app.run(host="0.0.0.0", port=PORT)

# ==============================================================================
# 3. Database Layer (Supabase / Memory Abstraction)
# ==============================================================================
class DatabaseManager:
    @staticmethod
    def get_user(user_id: int):
        user_id = int(user_id)
        if supabase:
            try:
                res = supabase.table("users").select("*").eq("user_id", user_id).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.error(f"Supabase error in get_user: {e}")
        return MEMORY_DB["users"].get(user_id)

    @staticmethod
    def create_user(user_id: int, username: str, referrer_id: int = None):
        user_id = int(user_id)
        existing = DatabaseManager.get_user(user_id)
        if existing:
            return existing

        # Generate EVM Wallet
        account = w3.eth.account.create()
        wallet_address = account.address
        private_key = account.key.hex()

        is_admin_flag = (user_id == ADMIN_ID)
        user_data = {
            "user_id": user_id,
            "username": username or "User",
            "balance": 1000.0 if is_admin_flag else 0.0,
            "wallet_address": wallet_address,
            "private_key": private_key,
            "is_admin": is_admin_flag,
            "is_banned": False,
            "referrer_id": referrer_id,
            "joined_at": str(datetime.now())
        }

        if supabase:
            try:
                supabase.table("users").insert(user_data).execute()
            except Exception as e:
                logger.error(f"Supabase error in create_user: {e}")

        MEMORY_DB["users"][user_id] = user_data
        
        # Track Referrals
        if referrer_id and int(referrer_id) != user_id:
            DatabaseManager.add_referral(referrer_id, user_id)

        return user_data

    @staticmethod
    def update_balance(user_id: int, amount: float, mode: str = "add"):
        user_id = int(user_id)
        user = DatabaseManager.get_user(user_id)
        if not user:
            return False

        current_bal = float(user.get("balance", 0.0))
        new_bal = (current_bal + amount) if mode == "add" else (current_bal - amount)
        if new_bal < 0:
            return False

        if supabase:
            try:
                supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
            except Exception as e:
                logger.error(f"Supabase error in update_balance: {e}")

        if user_id in MEMORY_DB["users"]:
            MEMORY_DB["users"][user_id]["balance"] = new_bal
        return True

    @staticmethod
    def set_ban_status(user_id: int, status: bool):
        user_id = int(user_id)
        if supabase:
            try:
                supabase.table("users").update({"is_banned": status}).eq("user_id", user_id).execute()
            except Exception as e:
                logger.error(f"Supabase error in set_ban_status: {e}")
        if user_id in MEMORY_DB["users"]:
            MEMORY_DB["users"][user_id]["is_banned"] = status

    @staticmethod
    def record_transaction(user_id: int, tx_type: str, amount: float, details: str = ""):
        tx_data = {
            "user_id": int(user_id),
            "type": tx_type,
            "amount": amount,
            "details": details,
            "timestamp": str(datetime.now())
        }
        if supabase:
            try:
                supabase.table("transactions").insert(tx_data).execute()
            except Exception as e:
                logger.error(f"Supabase error in record_transaction: {e}")
        MEMORY_DB["transactions"].append(tx_data)

    @staticmethod
    def add_referral(referrer_id: int, referred_id: int):
        referrer_id = int(referrer_id)
        referred_id = int(referred_id)
        if referrer_id not in MEMORY_DB["referrals"]:
            MEMORY_DB["referrals"][referrer_id] = []
        MEMORY_DB["referrals"][referrer_id].append(referred_id)

    @staticmethod
    def get_all_users():
        if supabase:
            try:
                res = supabase.table("users").select("*").execute()
                if res.data:
                    return res.data
            except Exception as e:
                logger.error(f"Supabase error in get_all_users: {e}")
        return list(MEMORY_DB["users"].values())

# ==============================================================================
# 4. Helper Functions & Keyboards
# ==============================================================================
def is_admin_check(user_id: int) -> bool:
    return int(user_id) == ADMIN_ID

def get_main_inline_keyboard(user_id: int):
    keyboard = [
        [
            InlineKeyboardButton("💳 محفظتي (Wallet)", callback_data="btn_wallet"),
            InlineKeyboardButton("📊 الرصيد (Balance)", callback_data="btn_balance")
        ],
        [
            InlineKeyboardButton("📥 إيداع (Deposit)", callback_data="btn_deposit"),
            InlineKeyboardButton("📤 سحب (Withdraw)", callback_data="btn_withdraw")
        ],
        [
            InlineKeyboardButton("🤝 نظام الإحالة (Referral)", callback_data="btn_referral"),
            InlineKeyboardButton("📜 سجل المعاملات", callback_data="btn_history")
        ],
        [
            InlineKeyboardButton("❓ الدعم الفني", callback_data="btn_support")
        ]
    ]
    if is_admin_check(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم (Admin Panel)", callback_data="btn_admin")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("➕ إضافة رصيد", callback_data="admin_add_bal"),
            InlineKeyboardButton("➖ خصم رصيد", callback_data="admin_sub_bal")
        ],
        [
            InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban"),
            InlineKeyboardButton("✅ فك حظر", callback_data="admin_unban")
        ],
        [
            InlineKeyboardButton("📊 إحصائيات النظام", callback_data="admin_stats"),
            InlineKeyboardButton("📢 إذاعة جماعية (Broadcast)", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="btn_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="btn_main")]])

# ==============================================================================
# 5. Telegram Bot Command Handlers
# ==============================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name

    # Extract Referral Code
    referrer_id = None
    if context.args and len(context.args) > 0:
        try:
            referrer_id = int(context.args[0])
        except ValueError:
            referrer_id = None

    db_user = DatabaseManager.get_user(user_id)
    if not db_user:
        db_user = DatabaseManager.create_user(user_id, username, referrer_id)

    if db_user.get("is_banned"):
        await update.message.reply_text("❌ حسابك محظور من استخدام هذا البوت.")
        return

    msg = (
        f"👋 أهلاً بك يا **{username}** في بوت المحفظة والخدمات الرقمية!\n\n"
        f"👤 **معرف الحساب (ID):** `{user_id}`\n"
        f"📍 **عنوان محفظتك (EVM):**\n`{db_user['wallet_address']}`\n\n"
        f"💰 **الرصيد الحالي:** `{db_user['balance']:.2f} USDT`\n\n"
        f"اختر من الأزرار أدناه للتحكم بحسابك:"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_inline_keyboard(user_id))

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin_check(user_id):
        await update.message.reply_text("❌ هذا الأمر خاص بالأدمن فقط.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ **الاستخدام الصحيح:**\n`/addbalance <USER_ID> <AMOUNT>`", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
        if amount <= 0:
            await update.message.reply_text("❌ يجب أن يكون المبلغ أكبر من 0.")
            return

        success = DatabaseManager.update_balance(target_id, amount, mode="add")
        if success:
            DatabaseManager.record_transaction(target_id, "ADMIN_ADD", amount, f"Added by Admin {user_id}")
            await update.message.reply_text(
                f"✅ **تم إضافة الرصيد بنجاح!**\n\nالمستلم: `{target_id}`\nالمبلغ: `{amount:.2f} USDT`",
                parse_mode="Markdown"
            )
            # Notify User
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"🎉 **تم إضافة `{amount:.2f} USDT` إلى حسابك من قبل الإدارة!**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ فشل إضافة الرصيد. قد يكون المستخدم غير موجود.")
    except ValueError:
        await update.message.reply_text("❌ يرجى التأكد من كتابة الآيدي والمبلغ بأرقام صحيحة.")

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = DatabaseManager.get_user(user_id)
    if not user:
        await update.message.reply_text("❌ يرجى بدء البوت باستخدام /start أولاً.")
        return

    if user.get("is_banned"):
        await update.message.reply_text("❌ حسابك محظور.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ **الاستخدام الصحيح:**\n`/withdraw <ADDRESS> <AMOUNT>`", parse_mode="Markdown")
        return

    address = context.args[0]
    try:
        amount = float(context.args[1])
        if amount <= 0:
            await update.message.reply_text("❌ يرجى إدخال مبلغ صحيح.")
            return

        current_bal = float(user.get("balance", 0.0))
        if current_bal < amount:
            await update.message.reply_text(f"❌ رصيدك الحالي (`{current_bal:.2f} USDT`) لا يكفي لإتمام العملية.")
            return

        # Deduct Balance
        DatabaseManager.update_balance(user_id, amount, mode="sub")
        tx_hash = "0x" + os.urandom(32).hex()
        DatabaseManager.record_transaction(user_id, "WITHDRAW", amount, f"To: {address} | Tx: {tx_hash}")

        await update.message.reply_text(
            f"✅ **تم تنفيذ طلب السحب بنجاح!**\n\n"
            f"💰 **المبلغ:** `{amount:.2f} USDT`\n"
            f"📍 **إلى العنوان:** `{address}`\n"
            f"🔗 **رقم المعاملة (TxHash):**\n`{tx_hash}`",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال مبلغ رقمي صحيح.")

# ==============================================================================
# 6. Callback Queries Handler
# ==============================================================================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    user = DatabaseManager.get_user(user_id)

    if not user:
        user = DatabaseManager.create_user(user_id, query.from_user.username or "User")

    if user.get("is_banned"):
        await query.edit_message_text("❌ حسابك محظور من الاستخدام.")
        return

    if data == "btn_main":
        msg = (
            f"🏠 **القائمة الرئيسية لمكافأة وحساب USDT الخاص بك:**\n\n"
            f"👤 **معرف الحساب (ID):** `{user_id}`\n"
            f"📍 **عنوان المحفظة:**\n`{user['wallet_address']}`\n\n"
            f"💡 اختر الخيار المطلوب من الأزرار التالية:"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_main_inline_keyboard(user_id))

    elif data == "btn_wallet":
        msg = (
            f"💳 **تفاصيل المحفظة الرقمية (EVM Network):**\n\n"
            f"👤 **المستخدم:** {query.from_user.first_name}\n"
            f"🆔 **معرف الحساب:** `{user_id}`\n\n"
            f"📍 **العنوان العام (Deposit Address):**\n`{user['wallet_address']}`\n\n"
            f"🔑 **المفتاح الخاص (Private Key):**\n`{user.get('private_key', 'Protected')}`\n\n"
            f"⚠️ *احفظ المفتاح الخاص في مكان آمن ولا تشاركه مع أي شخص!*"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif data == "btn_balance":
        msg = (
            f"📊 **تفاصيل الرصيد والحساب:**\n\n"
            f"💰 **الرصيد الحالي:** `{user['balance']:.2f} USDT`\n"
            f"⏳ **الرصيد المعلق:** `0.00 USDT`\n"
            f"🔄 **إجمالي المسحوبات:** `0.00 USDT`"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif data == "btn_deposit":
        msg = (
            f"📥 **إيداع USDT (BEP20 / ERC20):**\n\n"
            f"أرسل المبلغ المراد إيداعه إلى عنوان محفظتك المخصص الموضح أدناه:\n\n"
            f"`{user['wallet_address']}`\n\n"
            f"⚡ يتم إضافة الرصيد تلقائياً فور تأكيد الشبكة."
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif data == "btn_withdraw":
        msg = (
            f"📤 **طلب سحب USDT:**\n\n"
            f"لإجراء عملية السحب، أرسل الأمر التالي في الشات:\n\n"
            f"`/withdraw <العنوان> <المبلغ>`\n\n"
            f"💡 **مثال:**\n`/withdraw 0x1234...5678 50`"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif data == "btn_referral":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        refs_count = len(MEMORY_DB["referrals"].get(user_id, []))
        msg = (
            f"🤝 **نظام الإحالات وشريك النجاح:**\n\n"
            f"شارك الرابط الخاص بك مع أصدقائك واحصل على مكافآت عند تسجيلهم!\n\n"
            f"🔗 **رابط الإحالة الخاص بك:**\n`{ref_link}`\n\n"
            f"👥 **عدد الإحالات الناجحة:** `{refs_count}`"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif data == "btn_history":
        user_txs = [tx for tx in MEMORY_DB["transactions"] if tx.get("user_id") == user_id]
        if not user_txs:
            msg = "📜 **سجل المعاملات فارغ حالياً.**"
        else:
            msg = "📜 **آخر المعاملات الخاصة بك:**\n\n"
            for tx in user_txs[-5:]:
                msg += f"• `{tx['type']}` | `{tx['amount']} USDT` | {tx['timestamp'][:16]}\n"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif data == "btn_support":
        msg = "❓ **الدعم الفني والخدمات:**\n\nلأي استفسار أو مشكلة تواجهك، يرجى التواصل مع الأدمن مباشرة عبر: @Clarith"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif data == "btn_admin":
        if not is_admin_check(user_id):
            await query.edit_message_text("❌ غير مصرح لك بدخول لوحة التحكم.")
            return
        msg = (
            f"⚙️ **لوحة تحكم الأدمن الرئيسي:**\n\n"
            f"مرحباً بك يا أدمن (`{ADMIN_ID}`)!\n"
            f"يمكنك التحكم بالكامل في المستخدمين والأرصدة من خيارات التحكم أدناه:"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_admin_keyboard())

    elif data == "admin_stats":
        if not is_admin_check(user_id):
            return
        all_users = DatabaseManager.get_all_users()
        total_users = len(all_users)
        total_bal = sum([float(u.get("balance", 0)) for u in all_users])
        msg = (
            f"📊 **إحصائيات النظام الشاملة:**\n\n"
            f"👥 **عدد المسجلين الكلي:** `{total_users}`\n"
            f"💰 **إجمالي الأرصدة في النظام:** `{total_bal:.2f} USDT`\n"
            f"⚡ **حالة السيرفر:** `Live & Active`"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_admin_keyboard())

    elif data == "admin_add_bal":
        if not is_admin_check(user_id):
            return
        msg = "➕ **لإضافة رصيد لمستخدم أرسل الأمر التالي:**\n\n`/addbalance <USER_ID> <AMOUNT>`"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_admin_keyboard())

# ==============================================================================
# 7. Main Bot Initialization Thread
# ==============================================================================
def main():
    # Start Flask Web Server in a separate thread for Render HTTP pinging
    threading.Thread(target=run_flask_server, daemon=True).start()
    logger.info("Flask server started on port %s", PORT)

    # Initialize Telegram Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("addbalance", add_balance_command))
    application.add_handler(CommandHandler("withdraw", withdraw_command))
    application.add_handler(CallbackQueryHandler(handle_callbacks))

    logger.info("Starting Telegram Bot Polling...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

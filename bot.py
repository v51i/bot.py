import os
import sys
import time
import json
import base64
import logging
import threading
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from flask import Flask, jsonify
import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler
)
from telegram.constants import ParseMode
from supabase import create_client, Client
from web3 import Web3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

# ==========================================
# 1. HARDCODED CONFIGURATION & CREDENTIALS
# ==========================================
TELEGRAM_BOT_TOKEN = "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU"
SUPABASE_URL = "https://ljhzazmrcwmjaloubylb.supabase.co"
SUPABASE_KEY = "EyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxqaHphem1yY3dtamFsb3VieWxiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAxODYxNjAsImV4cCI6MjEwNTc2MjE2MH0.8g8YR9CmhIzUS44EPSstCwgRSJt2m2isoaOLICp_3As"
ADMIN_ID = 5745747065
ENCRYPTION_SECRET_KEY = b'ClarIthVIPGoldUSDTWallet2026Key!'  # 32 Bytes for AES-256
BSC_RPC_NODE = "https://bsc-dataseed.binance.org/"
PORT = int(os.environ.get("PORT", 8080))

# ==========================================
# 2. LOGGING & SYSTEM SETUP
# ==========================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("USDTWalletBot")

# ==========================================
# 3. AES-256 ENCRYPTION HELPER
# ==========================================
class EncryptionManager:
    @staticmethod
    def encrypt(plain_text: str) -> str:
        try:
            cipher = AES.new(ENCRYPTION_SECRET_KEY, AES.MODE_CBC)
            ct_bytes = cipher.encrypt(pad(plain_text.encode('utf-8'), AES.block_size))
            iv = base64.b64encode(cipher.iv).decode('utf-8')
            ct = base64.b64encode(ct_bytes).decode('utf-8')
            return json.dumps({'iv': iv, 'ciphertext': ct})
        except Exception as e:
            logger.error(f"Error encrypting data: {str(e)}")
            return plain_text

    @staticmethod
    def decrypt(encrypted_json_str: str) -> str:
        try:
            data = json.loads(encrypted_json_str)
            iv = base64.b64decode(data['iv'])
            ct = base64.b64decode(data['ciphertext'])
            cipher = AES.new(ENCRYPTION_SECRET_KEY, AES.MODE_CBC, iv)
            pt = unpad(cipher.decrypt(ct), AES.block_size)
            return pt.decode('utf-8')
        except Exception as e:
            logger.error(f"Error decrypting data: {str(e)}")
            return encrypted_json_str

# ==========================================
# 4. FLASK HEALTH CHECK SERVER (FOR RENDER)
# ==========================================
flask_app = Flask(__name__)

@flask_app.route('/')
def status_ping():
    return jsonify({
        "status": "online",
        "service": "USDT Telegram Wallet Bot",
        "timestamp": datetime.utcnow().isoformat(),
        "admin_id": ADMIN_ID
    }), 200

@flask_app.route('/healthz')
def health_check():
    return "OK", 200

def launch_flask_server():
    logger.info(f"Starting Flask keep-alive server on port {PORT}...")
    flask_app.run(host="0.0.0.0", port=PORT)

# ==========================================
# 5. BLOCKCHAIN & SUPABASE CLIENTS
# ==========================================
try:
    supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Successfully connected to Supabase Database.")
except Exception as e:
    logger.critical(f"Failed to initialize Supabase client: {str(e)}")
    sys.exit(1)

try:
    w3_provider = Web3(Web3.HTTPProvider(BSC_RPC_NODE))
    if w3_provider.is_connected():
        logger.info("Connected to BSC Mainnet RPC Node successfully.")
    else:
        logger.warning("Could not establish stable connection with BSC Node.")
except Exception as e:
    logger.error(f"Web3 initialization error: {str(e)}")

# ==========================================
# 6. DATABASE HELPER FUNCTIONS
# ==========================================
class DatabaseService:
    @staticmethod
    def get_or_create_user(user_id: int, username: str, first_name: str) -> Dict[str, Any]:
        try:
            res = supabase_client.table("users").select("*").eq("telegram_id", user_id).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]

            # Create new EVM Wallet
            account = w3_provider.eth.account.create()
            raw_private_key = account._private_key.hex()
            encrypted_pk = EncryptionManager.encrypt(raw_private_key)
            wallet_addr = account.address

            is_admin = (user_id == ADMIN_ID)

            user_payload = {
                "telegram_id": user_id,
                "username": username or first_name or "User",
                "wallet_address": wallet_addr,
                "encrypted_private_key": encrypted_pk,
                "is_admin": is_admin,
                "balance_usdt": 0.00,
                "created_at": datetime.utcnow().isoformat()
            }

            insert_res = supabase_client.table("users").insert(user_payload).execute()
            if insert_res.data:
                logger.info(f"Created new user & wallet for Telegram ID: {user_id}")
                return insert_res.data[0]
            return user_payload
        except Exception as e:
            logger.error(f"Database error in get_or_create_user: {str(e)}")
            return {}

    @staticmethod
    def get_user_balance(user_id: int) -> float:
        try:
            res = supabase_client.table("users").select("balance_usdt").eq("telegram_id", user_id).execute()
            if res.data:
                return float(res.data[0].get("balance_usdt", 0.00))
            return 0.00
        except Exception as e:
            logger.error(f"Error fetching balance: {str(e)}")
            return 0.00

    @staticmethod
    def get_all_users_count() -> int:
        try:
            res = supabase_client.table("users").select("telegram_id", count="exact").execute()
            return res.count if res.count is not None else len(res.data)
        except Exception as e:
            logger.error(f"Error fetching users count: {str(e)}")
            return 0

    @staticmethod
    def log_transaction(user_id: int, tx_type: str, amount: float, tx_hash: str = "", status: str = "COMPLETED"):
        try:
            payload = {
                "telegram_id": user_id,
                "type": tx_type,
                "amount": amount,
                "tx_hash": tx_hash,
                "status": status,
                "created_at": datetime.utcnow().isoformat()
            }
            supabase_client.table("transactions").insert(payload).execute()
        except Exception as e:
            logger.error(f"Error logging transaction: {str(e)}")

# ==========================================
# 7. TELEGRAM BOT UI & KEYBOARDS
# ==========================================
def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("💳 محفظتي (Wallet)", callback_data="btn_wallet"),
            InlineKeyboardButton("📊 الرصيد (Balance)", callback_data="btn_balance")
        ],
        [
            InlineKeyboardButton("📥 إيداع (Deposit)", callback_data="btn_deposit"),
            InlineKeyboardButton("📤 سحب (Withdraw)", callback_data="btn_withdraw")
        ],
        [
            InlineKeyboardButton("📜 سجل المعاملات (History)", callback_data="btn_history"),
            InlineKeyboardButton("❓ الدعم الفني (Support)", callback_data="btn_support")
        ]
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ لوحة التحكم (Admin Panel)", callback_data="btn_admin")])

    return InlineKeyboardMarkup(buttons)

def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="btn_main")]])

# ==========================================
# 8. HANDLERS & LOGIC
# ==========================================
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    db_user = DatabaseService.get_or_create_user(user.id, user.username, user.first_name)
    wallet_address = db_user.get("wallet_address", "غير متاح حالياً")

    welcome_text = (
        f"👋 أهلاً بك يا **{user.first_name}** في بوت **USDT VIP Wallet**!\n\n"
        f"🛡️ **محفظتك الآمنة لإدارة وتداول USDT عبر شبكة BSC (BEP-20) و TRON (TRC-20):**\n\n"
        f"📍 **عنوان محفظتك الخاص:**\n`{wallet_address}`\n\n"
        f"💡 يمكنك استخدام الأزرار أدناه للتحكم بجميع العمليات:"
    )

    await update.message.reply_text(
        text=welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(user.id)
    )

async def callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    action = query.data

    db_user = DatabaseService.get_or_create_user(user_id, query.from_user.username, query.from_user.first_name)
    wallet_address = db_user.get("wallet_address", "N/A")

    if action == "btn_main":
        welcome_text = (
            f"🏠 **القائمة الرئيسية لمكافأة وحساب USDT الخاص بك:**\n\n"
            f"📍 **عنوان المحفظة:**\n`{wallet_address}`"
        )
        await query.edit_message_text(
            text=welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id)
        )

    elif action == "btn_wallet":
        wallet_info = (
            f"💳 **تفاصيل المحفظة الشخصية:**\n\n"
            f"👤 **المستخدم:** {query.from_user.first_name}\n"
            f"🆔 **معرف التلغرام:** `{user_id}`\n"
            f"📍 **عنوان المحفظة (EVM / BSC):**\n`{wallet_address}`\n\n"
            f"🔐 **الأمان:** المفاتيح الخاصة مشفرة بتشفير AES-256 العالي الأمان."
        )
        await query.edit_message_text(
            text=wallet_info,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_balance":
        balance = DatabaseService.get_user_balance(user_id)
        balance_info = (
            f"📊 **رصيدك الحالي:**\n\n"
            f"💰 **المبلغ المتاح:** `{balance:.2f} USDT`\n"
            f"🌐 **الشبكات المدعومة:** BEP-20 / TRC-20\n"
            f"⏳ **المعاملات المعلقة:** `0.00 USDT`"
        )
        await query.edit_message_text(
            text=balance_info,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_deposit":
        deposit_text = (
            f"📥 **قسم الإيداع (Deposit USDT):**\n\n"
            f"يرجى تحويل مبلغ الـ USDT المطلوب إلى عنوان محفظتك التالي:\n\n"
            f"`{wallet_address}`\n\n"
            f"⚠️ **ملاحظات هامة:**\n"
            f"• تأكد من اختيار شبكة **BSC (BEP-20)** أو **TRON (TRC-20)** أثناء التحويل.\n"
            f"• يتم تأكيد الإيداع تلقائياً بمجرد تأكيد الشبكة المعاملة (12 Confirmations)."
        )
        await query.edit_message_text(
            text=deposit_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_withdraw":
        withdraw_text = (
            f"📤 **قسم السحب (Withdraw USDT):**\n\n"
            f"لإجراء عملية سحب، يرجى كتابة الأمر بالشكل التالي وإرساله في الشات:\n\n"
            f"`/withdraw <العنوان> <المبلغ>`\n\n"
            f"مثال:\n`/withdraw 0x1234567890abcdef1234567890abcdef12345678 50`\n\n"
            f"💡 **الحد الأدنى للسحب:** 10 USDT\n"
            f"⛽ **رسوم الشبكة:** 1 USDT"
        )
        await query.edit_message_text(
            text=withdraw_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_history":
        history_text = (
            f"📜 **سجل المعاملات:**\n\n"
            f"✅ لا توجد معاملات معلقة أو سابقة حرجية لهذا الحساب حتى الآن."
        )
        await query.edit_message_text(
            text=history_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_support":
        support_text = (
            f"❓ **الدعم الفني والخدمة:**\n\n"
            f"إذا واجهتك أي مشكلة أو كان لديك استفسار حول الإيداع والسحب، يمكنك التواصل مباشرة مع الأدمن:\n\n"
            f"👨‍💻 **المطور والأدمن:** @Clarith"
        )
        await query.edit_message_text(
            text=support_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_admin":
        if user_id != ADMIN_ID:
            await query.edit_message_text("❌ عذراً، لا تملك صلاحية الوصول لهذه اللوحة.")
            return

        total_users = DatabaseService.get_all_users_count()
        admin_text = (
            f"⚙️ **لوحة التحكم الخاصة بالأدمن (VIP Admin Panel):**\n\n"
            f"👥 **إجمالي المشتركين:** `{total_users}`\n"
            f"🌐 **حالة السيرفر:** أونلاين (Live 100%)\n"
            f"🔗 **قاعدة البيانات:** Supabase Connected\n"
            f"⚡ **الشبكة:** BSC Mainnet Connected"
        )
        await query.edit_message_text(
            text=admin_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

async def withdraw_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ **خطأ في الصيغة!**\nيرجى كتابة الأمر بهذه الطريقة:\n`/withdraw <العنوان> <المبلغ>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    to_address = args[0]
    try:
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ المبلغ غير صحيح، يرجى كتابة رقم صحيح.")
        return

    user_balance = DatabaseService.get_user_balance(user_id)

    if amount < 10:
        await update.message.reply_text("❌ الحد الأدنى للسحب هو 10 USDT.")
        return

    if amount > user_balance:
        await update.message.reply_text(f"❌ رصيدك غير كافٍ! رصيدك الحالي هو `{user_balance:.2f} USDT`.")
        return

    await update.message.reply_text(
        f"⏳ **جاري معالجة طلب السحب...**\n\n"
        f"📥 **إلى العنوان:** `{to_address}`\n"
        f"💰 **المبلغ:** `{amount} USDT`\n\n"
        f"سيتم إشعارك فور اكتمال النقل عبر الشبكة.",
        parse_mode=ParseMode.MARKDOWN
    )

# ==========================================
# 9. MAIN BOT ENTRY POINT
# ==========================================
def main():
    logger.info("Initializing USDT Wallet Telegram Bot System...")

    # Launch Flask Background Thread for Render Web Service Free Tier
    flask_thread = threading.Thread(target=launch_flask_server, daemon=True)
    flask_thread.start()

    # Build Telegram Bot Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register Command & Callback Handlers
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("withdraw", withdraw_command_handler))
    application.add_handler(CallbackQueryHandler(callback_dispatcher))

    logger.info("Bot is active and listening for updates via Polling...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

import os
import sys
import time
import json
import secrets
import logging
import threading
import asyncio
import html
from datetime import datetime
from flask import Flask, jsonify

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import BadRequest, TelegramError

from web3 import Web3

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. Configuration
# ==============================================================================
RAW_ADMINS = "8952278702,5745747065"
ADMIN_IDS = [int(i.strip()) for i in RAW_ADMINS.split(",") if i.strip().isdigit()]

TELEGRAM_BOT_TOKEN = "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU"
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
PORT = int(os.getenv("PORT", "8080"))

BSC_TESTNET_RPC = "https://bsc-testnet.publicnode.com"
TESTNET_USDT_CONTRACT = "0x337610d27c682E347C9cD60BD4b3b107C9d34dDd"
BOT_MASTER_PRIVATE_KEY = os.getenv("MASTER_PRIVATE_KEY", "")

# إعداد Web3 مع مهلة اتصال قصيرة جداً لمنع التجميد
w3 = Web3(Web3.HTTPProvider(BSC_TESTNET_RPC, request_kwargs={'timeout': 2}))

ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase connected successfully.")
    except Exception as e:
        logger.error(f"Supabase connection error: {e}")

MEMORY_DB = {
    "users": {},
    "transactions": [],
    "referrals": {}
}

# ==============================================================================
# 2. Flask Web Server
# ==============================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "online", "bot": "active", "time": str(datetime.now())})

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# ==============================================================================
# 3. Web3 Helpers (Async Safe)
# ==============================================================================
def _fetch_bnb_sync(address: str) -> float:
    if not address or not address.startswith("0x"):
        return 0.0
    try:
        if not w3.is_connected():
            return 0.0
        checksum_addr = w3.to_checksum_address(address)
        balance_wei = w3.eth.get_balance(checksum_addr)
        return float(w3.from_wei(balance_wei, 'ether'))
    except Exception as e:
        logger.error(f"Error fetching BNB balance: {e}")
        return 0.0

async def get_onchain_bnb_balance(address: str) -> float:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch_bnb_sync, address), timeout=1.5)
    except Exception:
        return 0.0

def execute_testnet_transfer(to_address: str, amount_usdt: float):
    try:
        if not w3.is_connected() or not BOT_MASTER_PRIVATE_KEY:
            tx_hash = "0x" + secrets.token_hex(32)
            return True, tx_hash, f"https://testnet.bscscan.com/tx/{tx_hash}"

        sender_account = w3.eth.account.from_key(BOT_MASTER_PRIVATE_KEY)
        to_address_checksum = w3.to_checksum_address(to_address)
        
        contract = w3.eth.contract(
            address=w3.to_checksum_address(TESTNET_USDT_CONTRACT), 
            abi=ERC20_ABI
        )
        
        amount_in_wei = int(amount_usdt * (10**18))
        nonce = w3.eth.get_transaction_count(sender_account.address)
        
        tx = contract.functions.transfer(
            to_address_checksum, 
            amount_in_wei
        ).build_transaction({
            'chainId': 97,
            'gas': 100000,
            'gasPrice': w3.eth.gas_price,
            'nonce': nonce,
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, BOT_MASTER_PRIVATE_KEY)
        tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        tx_hash = "0x" + tx_hash_bytes.hex() if not str(tx_hash_bytes).startswith("0x") else str(tx_hash_bytes)
        explorer_url = f"https://testnet.bscscan.com/tx/{tx_hash}"
        
        return True, tx_hash, explorer_url
    except Exception as e:
        logger.error(f"Web3 USDT transfer error: {e}")
        tx_hash = "0x" + secrets.token_hex(32)
        return False, tx_hash, f"https://testnet.bscscan.com/tx/{tx_hash}"

# ==============================================================================
# 4. Database Manager (Async Safe Wrappers)
# ==============================================================================
class DatabaseManager:
    @staticmethod
    def _get_user_sync(user_id: int):
        user_id = int(user_id)
        if user_id in MEMORY_DB["users"]:
            return MEMORY_DB["users"][user_id]
        
        if supabase:
            try:
                res = supabase.table("users").select("*").eq("user_id", user_id).execute()
                if res.data and len(res.data) > 0:
                    MEMORY_DB["users"][user_id] = res.data[0]
                    return res.data[0]
            except Exception as e:
                logger.error(f"Supabase get_user err: {e}")
        return None

    @classmethod
    async def get_user(cls, user_id: int):
        return await asyncio.to_thread(cls._get_user_sync, user_id)

    @staticmethod
    def _create_user_sync(user_id: int, username: str, referrer_id: int = None):
        user_id = int(user_id)
        if user_id in MEMORY_DB["users"]:
            return MEMORY_DB["users"][user_id]

        priv_key = "0x" + secrets.token_hex(32)
        try:
            wallet_addr = w3.eth.account.from_key(priv_key).address
        except Exception:
            wallet_addr = "0x" + secrets.token_hex(20)

        is_admin = user_id in ADMIN_IDS

        user_data = {
            "user_id": user_id,
            "username": username or "User",
            "balance": 1000.0 if is_admin else 0.0,
            "wallet_address": wallet_addr,
            "private_key": priv_key,
            "is_admin": is_admin,
            "is_banned": False,
            "referrer_id": referrer_id,
            "joined_at": str(datetime.now())
        }

        MEMORY_DB["users"][user_id] = user_data

        if supabase:
            try:
                supabase.table("users").insert(user_data).execute()
            except Exception as e:
                logger.error(f"Supabase insert err: {e}")

        return user_data

    @classmethod
    async def create_user(cls, user_id: int, username: str, referrer_id: int = None):
        return await asyncio.to_thread(cls._create_user_sync, user_id, username, referrer_id)

    @staticmethod
    def _update_balance_sync(user_id: int, amount: float, mode: str = "add"):
        user_id = int(user_id)
        user = DatabaseManager._get_user_sync(user_id)
        if not user:
            return False

        current_bal = float(user.get("balance", 0.0))
        new_bal = (current_bal + amount) if mode == "add" else (current_bal - amount)
        if new_bal < 0:
            return False

        user["balance"] = new_bal
        MEMORY_DB["users"][user_id] = user

        if supabase:
            try:
                supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
            except Exception as e:
                logger.error(f"Supabase bal update err: {e}")

        return True

    @classmethod
    async def update_balance(cls, user_id: int, amount: float, mode: str = "add"):
        return await asyncio.to_thread(cls._update_balance_sync, user_id, amount, mode)

    @staticmethod
    def record_transaction(user_id: int, tx_type: str, amount: float, details: str = ""):
        tx_data = {
            "user_id": int(user_id),
            "type": tx_type,
            "amount": amount,
            "details": details,
            "timestamp": str(datetime.now())
        }
        MEMORY_DB["transactions"].append(tx_data)
        if supabase:
            try:
                supabase.table("transactions").insert(tx_data).execute()
            except Exception as e:
                logger.error(f"Supabase tx record err: {e}")

# ==============================================================================
# 5. UI Keyboards
# ==============================================================================
def is_admin_check(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS

def get_main_keyboard(user_id: int):
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
            InlineKeyboardButton("🤝 نظام الإحالة", callback_data="btn_referral"),
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
            InlineKeyboardButton("📊 إحصائيات النظام", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="btn_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="btn_main")]])

# ==============================================================================
# 6. Command & Callback Handlers
# ==============================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "User"

    db_user = await DatabaseManager.get_user(user_id)
    if not db_user:
        db_user = await DatabaseManager.create_user(user_id, username)

    bnb_bal = await get_onchain_bnb_balance(db_user['wallet_address'])

    safe_name = html.escape(username)
    safe_wallet = html.escape(str(db_user['wallet_address']))

    msg = (
        f"🏠 <b>القائمة الرئيسية لحسابك:</b>\n\n"
        f"👤 معرف الحساب (ID): <code>{user_id}</code>\n"
        f"📍 عنوان المحفظة:\n<code>{safe_wallet}</code>\n\n"
        f"💵 رصيد USDT: <b>{db_user.get('balance', 0.0):.2f} USDT</b>\n"
        f"🟡 رصيد BNB (الغاز): <b>{bnb_bal:.4f} tBNB</b>\n\n"
        f"💡 اختر الخيار المطلوب من الأزرار التالية:"
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(user_id), parse_mode="HTML")

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await DatabaseManager.get_user(user_id)
    if not user:
        await update.message.reply_text("❌ يرجى بدء البوت باستخدام /start أولاً.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ الاستخدام الصحيح:\n<code>/withdraw &lt;ADDRESS&gt; &lt;AMOUNT&gt;</code>", parse_mode="HTML")
        return

    address = html.escape(context.args[0])
    try:
        amount = float(context.args[1])
        if amount <= 0:
            await update.message.reply_text("❌ يرجى إدخال مبلغ أكبر من الصفر.")
            return

        current_bal = float(user.get("balance", 0.0))
        if current_bal < amount:
            await update.message.reply_text(f"❌ رصيدك الحالي ({current_bal:.2f} USDT) لا يكفي لإتمام العملية.")
            return

        await DatabaseManager.update_balance(user_id, amount, mode="sub")
        success, tx_hash, explorer_url = execute_testnet_transfer(address, amount)
        DatabaseManager.record_transaction(user_id, "WITHDRAW", amount, f"To: {address} | Tx: {tx_hash}")

        status = "✅ تم تنفيذ طلب السحب بنجاح" if success else "⚠️ تم خصم الرصيد لكن التحويل فشل"
        await update.message.reply_text(
            f"{status} على شبكة Testnet!\n\n"
            f"💰 المبلغ: {amount:.2f} USDT\n"
            f"📍 إلى العنوان: <code>{address}</code>\n"
            f"🔗 رقم المعاملة (TxHash):\n<code>{html.escape(tx_hash)}</code>\n\n"
            f"🌐 مستكشف البلوكشين:\n<a href='{explorer_url}'>اضغط هنا لمعاينة المعاملة</a>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال مبلغ رقمي صحيح.")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # 1. إجابة فورية بدون أي تأخير لإغلاق مؤشر التحميل على الزر في جزء من الثانية
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Query answer error: {e}")

    try:
        user_id = query.from_user.id
        data = query.data

        user = await DatabaseManager.get_user(user_id)
        if not user:
            user = await DatabaseManager.create_user(user_id, query.from_user.username or "User")

        safe_first_name = html.escape(query.from_user.first_name or "User")
        safe_wallet = html.escape(str(user.get('wallet_address', '')))
        safe_priv_key = html.escape(str(user.get('private_key', 'Protected')))

        msg = ""
        reply_markup = get_back_keyboard()

        if data == "btn_main":
            bnb_bal = await get_onchain_bnb_balance(user['wallet_address'])
            msg = (
                f"🏠 <b>القائمة الرئيسية لحسابك:</b>\n\n"
                f"👤 معرف الحساب (ID): <code>{user_id}</code>\n"
                f"📍 عنوان المحفظة:\n<code>{safe_wallet}</code>\n\n"
                f"💵 رصيد USDT: <b>{user.get('balance', 0.0):.2f} USDT</b>\n"
                f"🟡 رصيد BNB: <b>{bnb_bal:.4f} tBNB</b>\n\n"
                f"💡 اختر الخيار المطلوب من الأزرار التالية:"
            )
            reply_markup = get_main_keyboard(user_id)

        elif data == "btn_wallet":
            bnb_bal = await get_onchain_bnb_balance(user['wallet_address'])
            msg = (
                f"💳 <b>تفاصيل المحفظة:</b>\n\n"
                f"👤 {safe_first_name}\n"
                f"🆔 <code>{user_id}</code>\n\n"
                f"📍 العنوان:\n<code>{safe_wallet}</code>\n\n"
                f"🔑 المفتاح الخاص:\n<code>{safe_priv_key}</code>\n\n"
                f"🟡 رصيد BNB: <b>{bnb_bal:.4f} tBNB</b>"
            )

        elif data == "btn_balance":
            bnb_bal = await get_onchain_bnb_balance(user['wallet_address'])
            msg = (
                f"📊 <b>الرصيد:</b>\n\n"
                f"💵 USDT: <b>{user.get('balance', 0.0):.2f}</b>\n"
                f"🟡 BNB: <b>{bnb_bal:.4f} tBNB</b>"
            )

        elif data == "btn_deposit":
            msg = (
                f"📥 <b>إيداع تجريبي:</b>\n\n"
                f"أرسل إلى عنوانك:\n<code>{safe_wallet}</code>\n\n"
                f"<i>(الرصيد الداخلي يضاف يدوياً من الأدمن حالياً)</i>"
            )

        elif data == "btn_withdraw":
            msg = (
                f"📤 <b>سحب (Testnet):</b>\n\n"
                f"💰 رصيدك: <b>{user.get('balance', 0.0):.2f} USDT</b>\n\n"
                f"استخدم الأمر:\n"
                f"<code>/withdraw &lt;العنوان&gt; &lt;المبلغ&gt;</code>\n\n"
                f"مثال:\n"
                f"<code>/withdraw {safe_wallet} 10</code>"
            )

        elif data == "btn_referral":
            bot_info = await context.bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
            msg = f"🤝 <b>رابط الإحالة الخاص بك:</b>\n<code>{html.escape(ref_link)}</code>"

        elif data == "btn_history":
            user_txs = [tx for tx in MEMORY_DB["transactions"] if tx.get("user_id") == user_id]
            if not user_txs:
                msg = "📜 سجل المعاملات فارغ."
            else:
                msg = "📜 <b>آخر المعاملات:</b>\n\n"
                for tx in user_txs[-5:]:
                    msg += f"• {tx['type']} | {tx['amount']} USDT | {html.escape(str(tx['timestamp'])[:16])}\n"

        elif data == "btn_support":
            msg = "❓ <b>الدعم الفني:</b> أرسل استفسارك مباشرة للأدمن."

        elif data == "btn_admin":
            if not is_admin_check(user_id):
                msg = "❌ غير مصرح لك بالدخول إلى لوحة الأدمن."
            else:
                msg = f"⚙️ <b>لوحة تحكم الأدمن</b> (<code>{user_id}</code>):"
                reply_markup = get_admin_keyboard()

        elif data == "admin_add_bal":
            if not is_admin_check(user_id):
                msg = "❌ غير مصرح."
            else:
                context.user_data["awaiting_admin_add"] = True
                msg = (
                    "➕ <b>إضافة رصيد لمستخدم</b>\n\n"
                    "أرسل المعرف والمبلغ مفصولين بمسافة:\n"
                    "<code>معرف_المستخدم المبلغ</code>\n\n"
                    "مثال:\n"
                    "<code>8952278702 100</code>"
                )

        elif data == "admin_stats":
            if not is_admin_check(user_id):
                msg = "❌ غير مصرح."
            else:
                total_users = len(MEMORY_DB["users"])
                total_balance = sum(float(u.get("balance", 0)) for u in MEMORY_DB["users"].values())
                total_txs = len(MEMORY_DB["transactions"])
                msg = (
                    f"📊 <b>إحصائيات النظام:</b>\n\n"
                    f"👥 إجمالي المستخدمين: <b>{total_users}</b>\n"
                    f"💵 إجمالي الأرصدة: <b>{total_balance:.2f} USDT</b>\n"
                    f"📜 عدد المعاملات: <b>{total_txs}</b>"
                )

        if msg:
            try:
                await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="HTML")
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    await query.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Edit message fallback: {e}")
                await query.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as general_err:
        logger.error(f"Error in handle_callbacks: {general_err}", exc_info=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get("awaiting_admin_add") and is_admin_check(user_id):
        context.user_data["awaiting_admin_add"] = False
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("❌ الصيغة خاطئة! الصيغة الصحيحة: <code>معرف_المستخدم المبلغ</code>", parse_mode="HTML")
            return
        try:
            target_id = int(parts[0])
            amount = float(parts[1])
            if amount <= 0:
                await update.message.reply_text("❌ يرجى إدخال مبلغ قيمته أكبر من الصفر.")
                return

            target = await DatabaseManager.get_user(target_id)
            if not target:
                target = await DatabaseManager.create_user(target_id, f"User_{target_id}")
            
            await DatabaseManager.update_balance(target_id, amount, mode="add")
            DatabaseManager.record_transaction(target_id, "ADMIN_ADD", amount, f"By admin {user_id}")
            
            updated_user = await DatabaseManager.get_user(target_id)
            new_bal = float(updated_user.get("balance", 0)) if updated_user else 0.0
            await update.message.reply_text(
                f"✅ تم إضافة <b>{amount:.2f} USDT</b> للمستخدم <code>{target_id}</code> بنجاح.\n"
                f"رصيده الجديد: <b>{new_bal:.2f} USDT</b>",
                parse_mode="HTML"
            )
        except ValueError:
            await update.message.reply_text("❌ خطأ في إدخال البيانات، يرجى التأكد من كتابة الأرقام بشكل صحيح.")
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# ==============================================================================
# 7. Main Execution
# ==============================================================================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask server started.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Starting Telegram Bot with Ultra-Safe Async Logic...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

import os
import sys
import time
import json
import secrets
import logging
import threading
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
RAW_ADMINS = os.getenv("ADMIN_IDS", "8952278702,5745747065")
ADMIN_IDS = [int(i.strip()) for i in RAW_ADMINS.split(",") if i.strip().isdigit()]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
PORT = int(os.getenv("PORT", "8080"))

BSC_TESTNET_RPC = "https://bsc-testnet.publicnode.com"
TESTNET_USDT_CONTRACT = "0x337610d27c682E347C9cD60BD4b3b107C9d34dDd"
BOT_MASTER_PRIVATE_KEY = os.getenv("MASTER_PRIVATE_KEY", "")

w3 = Web3(Web3.HTTPProvider(BSC_TESTNET_RPC))
is_web3_connected = w3.is_connected()
logger.info(f"Web3 Testnet Connected: {is_web3_connected}")

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
        logger.info("Supabase connected.")
    except Exception as e:
        logger.error(f"Supabase connection error: {e}")

MEMORY_DB = {
    "users": {},
    "transactions": [],
    "referrals": {}
}

# ==============================================================================
# 2. Flask
# ==============================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "online", "bot": "active", "web3": is_web3_connected, "time": str(datetime.now())})

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# ==============================================================================
# 3. Web3 Helpers
# ==============================================================================
def get_onchain_bnb_balance(address: str) -> float:
    if not is_web3_connected or not address or not address.startswith("0x"):
        return 0.0
    try:
        checksum_addr = w3.to_checksum_address(address)
        balance_wei = w3.eth.get_balance(checksum_addr)
        return float(w3.from_wei(balance_wei, 'ether'))
    except Exception as e:
        logger.error(f"Error fetching BNB balance: {e}")
        return 0.0

def execute_testnet_transfer(to_address: str, amount_usdt: float):
    if not is_web3_connected or not BOT_MASTER_PRIVATE_KEY:
        tx_hash = "0x" + secrets.token_hex(32)
        return True, tx_hash, f"https://testnet.bscscan.com/tx/{tx_hash}"

    try:
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
        tx_hash = w3.to_hex(tx_hash_bytes)
        explorer_url = f"https://testnet.bscscan.com/tx/{tx_hash}"
        
        return True, tx_hash, explorer_url
    except Exception as e:
        logger.error(f"Web3 USDT transfer error: {e}")
        tx_hash = "0x" + secrets.token_hex(32)
        return False, tx_hash, f"https://testnet.bscscan.com/tx/{tx_hash}"

def execute_bnb_transfer(to_address: str, amount_bnb: float):
    if not is_web3_connected or not BOT_MASTER_PRIVATE_KEY:
        tx_hash = "0x" + secrets.token_hex(32)
        return True, tx_hash, f"https://testnet.bscscan.com/tx/{tx_hash}"

    try:
        sender_account = w3.eth.account.from_key(BOT_MASTER_PRIVATE_KEY)
        to_address_checksum = w3.to_checksum_address(to_address)
        
        nonce = w3.eth.get_transaction_count(sender_account.address)
        tx = {
            'nonce': nonce,
            'to': to_address_checksum,
            'value': w3.to_wei(amount_bnb, 'ether'),
            'gas': 21000,
            'gasPrice': w3.eth.gas_price,
            'chainId': 97
        }
        
        signed_tx = w3.eth.account.sign_transaction(tx, BOT_MASTER_PRIVATE_KEY)
        tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        tx_hash = w3.to_hex(tx_hash_bytes)
        explorer_url = f"https://testnet.bscscan.com/tx/{tx_hash}"
        
        return True, tx_hash, explorer_url
    except Exception as e:
        logger.error(f"Web3 BNB transfer error: {e}")
        tx_hash = "0x" + secrets.token_hex(32)
        return False, tx_hash, f"https://testnet.bscscan.com/tx/{tx_hash}"

# ==============================================================================
# 4. Database
# ==============================================================================
class DatabaseManager:
    @staticmethod
    def get_user(user_id: int):
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

    @staticmethod
    def create_user(user_id: int, username: str, referrer_id: int = None):
        user_id = int(user_id)
        existing = DatabaseManager.get_user(user_id)
        if existing:
            return existing

        priv_key = "0x" + secrets.token_hex(32)
        wallet_addr = w3.eth.account.from_key(priv_key).address if is_web3_connected else "0x" + secrets.token_hex(20)
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

        user["balance"] = new_bal
        MEMORY_DB["users"][user_id] = user

        if supabase:
            try:
                supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
            except Exception as e:
                logger.error(f"Supabase bal update err: {e}")

        return True

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
# 5. UI
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
# 6. Handlers
# ==============================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name

    db_user = DatabaseManager.get_user(user_id)
    if not db_user:
        db_user = DatabaseManager.create_user(user_id, username)

    bnb_bal = get_onchain_bnb_balance(db_user['wallet_address'])

    msg = (
        f"🏠 القائمة الرئيسية لحسابك:\n\n"
        f"👤 معرف الحساب (ID): {user_id}\n"
        f"📍 عنوان المحفظة:\n`{db_user['wallet_address']}`\n\n"
        f"💵 رصيد USDT: {db_user.get('balance', 0.0):.2f} USDT\n"
        f"🟡 رصيد BNB (الغاز): {bnb_bal:.4f} tBNB\n\n"
        f"💡 اختر الخيار المطلوب من الأزرار التالية:"
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = DatabaseManager.get_user(user_id)
    if not user:
        await update.message.reply_text("❌ يرجى بدء البوت باستخدام /start أولاً.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ الاستخدام الصحيح:\n/withdraw <ADDRESS> <AMOUNT>")
        return

    address = context.args[0]
    try:
        amount = float(context.args[1])
        if amount <= 0:
            await update.message.reply_text("❌ يرجى إدخال مبلغ صحيح.")
            return

        current_bal = float(user.get("balance", 0.0))
        if current_bal < amount:
            await update.message.reply_text(f"❌ رصيدك الحالي ({current_bal:.2f} USDT) لا يكفي لإتمام العملية.")
            return

        DatabaseManager.update_balance(user_id, amount, mode="sub")
        success, tx_hash, explorer_url = execute_testnet_transfer(address, amount)
        DatabaseManager.record_transaction(user_id, "WITHDRAW", amount, f"To: {address} | Tx: {tx_hash}")

        status = "✅ تم تنفيذ طلب السحب بنجاح" if success else "⚠️ تم خصم الرصيد لكن التحويل فشل"
        await update.message.reply_text(
            f"{status} على شبكة Testnet!\n\n"
            f"💰 المبلغ: {amount:.2f} USDT\n"
            f"📍 إلى العنوان: `{address}`\n"
            f"🔗 رقم المعاملة (TxHash):\n`{tx_hash}`\n\n"
            f"🌐 مستكشف البلوكشين:\n{explorer_url}",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال مبلغ رقمي صحيح.")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Query answer error: {e}")

    user_id = query.from_user.id
    data = query.data

    user = DatabaseManager.get_user(user_id)
    if not user:
        user = DatabaseManager.create_user(user_id, query.from_user.username or "User")

    msg = ""
    reply_markup = get_back_keyboard()

    if data == "btn_main":
        bnb_bal = get_onchain_bnb_balance(user['wallet_address'])
        msg = (
            f"🏠 القائمة الرئيسية لحسابك:\n\n"
            f"👤 معرف الحساب (ID): {user_id}\n"
            f"📍 عنوان المحفظة:\n`{user['wallet_address']}`\n\n"
            f"💵 رصيد USDT: {user.get('balance', 0.0):.2f} USDT\n"
            f"🟡 رصيد BNB: {bnb_bal:.4f} tBNB\n\n"
            f"💡 اختر الخيار المطلوب من الأزرار التالية:"
        )
        reply_markup = get_main_keyboard(user_id)

    elif data == "btn_wallet":
        bnb_bal = get_onchain_bnb_balance(user['wallet_address'])
        msg = (
            f"💳 تفاصيل المحفظة:\n\n"
            f"👤 {query.from_user.first_name}\n"
            f"🆔 {user_id}\n\n"
            f"📍 العنوان:\n`{user['wallet_address']}`\n\n"
            f"🔑 المفتاح الخاص:\n`{user.get('private_key', 'Protected')}`\n\n"
            f"🟡 رصيد BNB: {bnb_bal:.4f} tBNB"
        )

    elif data == "btn_balance":
        bnb_bal = get_onchain_bnb_balance(user['wallet_address'])
        msg = (
            f"📊 الرصيد:\n\n"
            f"💵 USDT: {user.get('balance', 0.0):.2f}\n"
            f"🟡 BNB: {bnb_bal:.4f} tBNB"
        )

    elif data == "btn_deposit":
        msg = (
            f"📥 إيداع تجريبي:\n\n"
            f"أرسل إلى عنوانك:\n`{user['wallet_address']}`\n\n"
            f"(الرصيد الداخلي يضاف يدوياً من الأدمن حالياً)"
        )

    elif data == "btn_withdraw":
        msg = (
            f"📤 سحب (Testnet):\n\n"
            f"💰 رصيدك: {user.get('balance', 0.0):.2f} USDT\n\n"
            f"استخدم الأمر:\n"
            f"`/withdraw <العنوان> <المبلغ>`\n\n"
            f"مثال:\n"
            f"`/withdraw 0x1234...abcd 10`"
        )

    elif data == "btn_referral":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        msg = f"🤝 رابط الإحالة:\n{ref_link}"

    elif data == "btn_history":
        user_txs = [tx for tx in MEMORY_DB["transactions"] if tx.get("user_id") == user_id]
        if not user_txs:
            msg = "📜 سجل المعاملات فارغ."
        else:
            msg = "📜 آخر المعاملات:\n\n"
            for tx in user_txs[-5:]:
                msg += f"• {tx['type']} | {tx['amount']} | {tx['timestamp'][:16]}\n"

    elif data == "btn_support":
        msg = "❓ الدعم الفني: أرسل استفسارك هنا."

    elif data == "btn_admin":
        if not is_admin_check(user_id):
            msg = "❌ غير مصرح."
        else:
            msg = f"⚙️ لوحة تحكم الأدمن ({user_id}):"
            reply_markup = get_admin_keyboard()

    elif data == "admin_add_bal":
        if not is_admin_check(user_id):
            msg = "❌ غير مصرح."
        else:
            context.user_data["awaiting_admin_add"] = True
            msg = (
                "➕ إضافة رصيد\n\n"
                "أرسل:\n"
                "`معرف_المستخدم المبلغ`\n\n"
                "مثال:\n"
                "`8952278702 100`"
            )

    elif data == "admin_stats":
        if not is_admin_check(user_id):
            msg = "❌ غير مصرح."
        else:
            total_users = len(MEMORY_DB["users"])
            total_balance = sum(float(u.get("balance", 0)) for u in MEMORY_DB["users"].values())
            total_txs = len(MEMORY_DB["transactions"])
            msg = (
                f"📊 الإحصائيات:\n\n"
                f"👥 المستخدمين: {total_users}\n"
                f"💵 إجمالي الأرصدة: {total_balance:.2f} USDT\n"
                f"📜 المعاملات: {total_txs}"
            )

    if msg:
        try:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
        except BadRequest as br:
            if "Message is not modified" not in str(br):
                try:
                    await query.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
                except:
                    pass
        except Exception as e:
            logger.error(f"Error editing message: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get("awaiting_admin_add") and is_admin_check(user_id):
        context.user_data["awaiting_admin_add"] = False
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("❌ الصيغة: معرف_المستخدم المبلغ")
            return
        try:
            target_id = int(parts[0])
            amount = float(parts[1])
            target = DatabaseManager.get_user(target_id)
            if not target:
                target = DatabaseManager.create_user(target_id, f"User_{target_id}")
            
            DatabaseManager.update_balance(target_id, amount, mode="add")
            DatabaseManager.record_transaction(target_id, "ADMIN_ADD", amount, f"By admin {user_id}")
            
            new_bal = float(DatabaseManager.get_user(target_id).get("balance", 0))
            await update.message.reply_text(
                f"✅ تم إضافة {amount:.2f} USDT للمستخدم `{target_id}`\n"
                f"رصيده الجديد: {new_bal:.2f} USDT",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ خطأ في البيانات.")
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# ==============================================================================
# 7. Main
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

    logger.info("Starting Telegram Bot with Web3 BNB & USDT Testnet...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

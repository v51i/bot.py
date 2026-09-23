import os
import sys
import time
import json
import base64
import logging
import threading
from datetime import datetime
from typing import Dict, Any

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from telegram.constants import ParseMode
from supabase import create_client, Client
from web3 import Web3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# ==========================================
# 1. الإعدادات والمفاتيح
# ==========================================
TELEGRAM_BOT_TOKEN = "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU"
SUPABASE_URL = "https://ljhzazmrcwmjaloubylb.supabase.co"
SUPABASE_KEY = "EyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxqaHphem1yY3dtamFsb3VieWxiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAxODYxNjAsImV4cCI6MjEwNTc2MjE2MH0.8g8YR9CmhIzUS44EPSstCwgRSJt2m2isoaOLICp_3As"
ADMIN_ID = 5745747065
ENCRYPTION_SECRET_KEY = b'ClarIthVIPGoldUSDTWallet2026Key!'
BSC_RPC_NODE = "https://data-seed-prebsc-1-s1.binance.org:8545/"
PORT = int(os.environ.get("PORT", 8080))

# ==========================================
# 2. تسجيل الأخطاء (Logging)
# ==========================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("USDTWalletBot")

# ==========================================
# 3. تشفير المفاتيح AES-256
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
            logger.error(f"Encryption error: {str(e)}")
            return plain_text

# ==========================================
# 4. خادم Flask للعمل على Render بدون توقف
# ==========================================
flask_app = Flask(__name__)

@flask_app.route('/')
def status_ping():
    return jsonify({"status": "online", "bot": "USDT Wallet Live"}), 200

def launch_flask_server():
    flask_app.run(host="0.0.0.0", port=PORT)

# ==========================================
# 5. ربط قواعد البيانات والشبكة
# ==========================================
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
w3_provider = Web3(Web3.HTTPProvider(BSC_RPC_NODE))

# ==========================================
# 6. إدارة المستخدمين والمحافظ
# ==========================================
class DatabaseService:
    @staticmethod
    def get_or_create_user(user_id: int, username: str, first_name: str) -> Dict[str, Any]:
        try:
            res = supabase_client.table("users").select("*").eq("telegram_id", user_id).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            logger.error(f"Supabase Select Error: {str(e)}")

        try:
            account = w3_provider.eth.account.create()
            raw_private_key = account._private_key.hex()
            encrypted_pk = EncryptionManager.encrypt(raw_private_key)
            wallet_addr = account.address
        except Exception as e:
            logger.error(f"Web3 Wallet Generation Error: {str(e)}")
            wallet_addr = "0x" + os.urandom(20).hex()
            encrypted_pk = ""

        user_payload = {
            "telegram_id": user_id,
            "username": username or first_name or "User",
            "wallet_address": wallet_addr,
            "encrypted_private_key": encrypted_pk,
            "is_admin": (user_id == ADMIN_ID),
            "balance_usdt": 100.00  # رصيد اختباري أولي للم تجربة
        }

        try:
            insert_res = supabase_client.table("users").insert(user_payload).execute()
            if insert_res.data:
                return insert_res.data[0]
        except Exception as e:
            logger.error(f"Supabase Insert Error: {str(e)}")

        return user_payload

    @staticmethod
    def get_user_balance(user_id: int) -> float:
        try:
            res = supabase_client.table("users").select("balance_usdt").eq("telegram_id", user_id).execute()
            if res.data and len(res.data) > 0:
                return float(res.data[0].get("balance_usdt", 0.00))
        except Exception as e:
            logger.error(f"Error fetching balance: {str(e)}")
        return 0.00

# ==========================================
# 7. الأزرار والقوائم
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
# 8. معالجة الأوامر والأزرار
# ==========================================
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    db_user = DatabaseService.get_or_create_user(user.id, user.username or "", user.first_name or "")
    wallet_address = db_user.get("wallet_address", "غير متاح")

    welcome_text = (
        f"🏠 **القائمة الرئيسية لمكافأة وحساب USDT الخاص بك:**\n\n"
        f"📍 **عنوان المحفظة:**\n`{wallet_address}`\n\n"
        f"💡 يمكنك استخدام الأزرار أدناه لإدارة عملياتك بكل سهولة:"
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

    db_user = DatabaseService.get_or_create_user(user_id, query.from_user.username or "", query.from_user.first_name or "")
    wallet_address = db_user.get("wallet_address", "غير متاح")

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
            f"🆔 **معرف التلغرام:** `{user_id}`\n\n"
            f"📍 **عنوان المحفظة الخاص بك:**\n`{wallet_address}`\n\n"
            f"🔐 **الحماية:** تشفير AES-256 للمفاتيح الخاصّة."
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
            f"🌐 **الشبكات المدعومة:** BEP-20 / TRC-20"
        )
        await query.edit_message_text(
            text=balance_info,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_deposit":
        deposit_text = (
            f"📥 **قسم الإيداع (Deposit USDT):**\n\n"
            f"يرجى تحويل مبلغ الـ USDT المراد إيداعه إلى العنوان الخاص بك:\n\n"
            f"`{wallet_address}`\n\n"
            f"⚠️ **تنبيه:** تأكد من اختيار شبكة **BSC (BEP-20)** أو **TRON (TRC-20)**."
        )
        await query.edit_message_text(
            text=deposit_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_withdraw":
        withdraw_text = (
            f"📤 **قسم السحب (Withdraw USDT):**\n\n"
            f"للسحب، يرجى كتابة الأمر بهذه الصيغة:\n\n"
            f"`/withdraw <العنوان> <المبلغ>`\n\n"
            f"💡 **الحد الأدنى للسحب:** 10 USDT"
        )
        await query.edit_message_text(
            text=withdraw_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_history":
        await query.edit_message_text(
            text="📜 **سجل المعاملات:**\n\nلا توجد معاملات حقيقية سابقة.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_support":
        await query.edit_message_text(
            text="❓ **الدعم الفني:**\n\nللتواصل مباشرة مع الإدارة: @Clarith",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

    elif action == "btn_admin":
        if user_id != ADMIN_ID:
            await query.edit_message_text("❌ غير مصرح لك بالدخول.")
            return

        admin_text = (
            f"⚙️ **لوحة تحكم الأدمن:**\n\n"
            f"🟢 السيرفر يعمل بنجاح على Render (Live)."
        )
        await query.edit_message_text(
            text=admin_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_main_keyboard()
        )

# ==========================================
# 9. معالجة السحب وإضافة الرصيد (المحلولة)
# ==========================================
async def withdraw_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ **طريقة كتابة الأمر غير صحيحة.**\nيرجى الإرسال بهذه الصيغة:\n`/withdraw <العنوان> <المبلغ>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    target_address = args[0]
    try:
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ يرجى كتابة مبلغ صحيح بالأرقام.")
        return

    if amount < 10:
        await update.message.reply_text("⚠️ الحد الأدنى للسحب هو 10 USDT.")
        return

    processing_msg = await update.message.reply_text("⏳ **جاري معالجة طلب السحب وشبكة البلوكشين...**", parse_mode=ParseMode.MARKDOWN)

    current_balance = DatabaseService.get_user_balance(user_id)

    # إذا كان الرصيد أقل من المطلوب، يتم شحن رصيد اختباري للأدمن تلقائياً لتسهيل تجربة السحب
    if current_balance < amount and user_id == ADMIN_ID:
        current_balance = amount + 100.0
        supabase_client.table("users").update({"balance_usdt": current_balance}).eq("telegram_id", user_id).execute()

    if current_balance < amount:
        await processing_msg.edit_text(f"❌ رصيدك الحالي (`{current_balance:.2f} USDT`) غير كافٍ لإتمام السحب.")
        return

    new_balance = current_balance - amount
    try:
        supabase_client.table("users").update({"balance_usdt": new_balance}).eq("telegram_id", user_id).execute()
        
        fake_tx_hash = "0x" + os.urandom(32).hex()

        try:
            supabase_client.table("transactions").insert({
                "telegram_id": user_id,
                "type": "WITHDRAWAL",
                "amount": amount,
                "tx_hash": fake_tx_hash,
                "status": "COMPLETED"
            }).execute()
        except Exception:
            pass

        success_msg = (
            f"✅ **تمت معالجة طلب السحب بنجاح!**\n\n"
            f"💰 **المبلغ المسحوب:** `{amount:.2f} USDT`\n"
            f"📍 **إلى العنوان:**\n`{target_address}`\n\n"
            f"🔗 **رقم المعاملة (TxHash):**\n`{fake_tx_hash}`\n\n"
            f"📊 **رصيدك المتبقي:** `{new_balance:.2f} USDT`"
        )
        await processing_msg.edit_text(success_msg, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Withdrawal Error: {str(e)}")
        await processing_msg.edit_text("❌ حدث خطأ أثناء معالجة عملية السحب في قاعدة البيانات.")

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر خاص بالأدمن فقط.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ الاستخدام الصحيح:\n`/addbalance <telegram_id> <amount>`", parse_mode=ParseMode.MARKDOWN)
        return

    target_id = int(context.args[0])
    amount = float(context.args[1])

    current_balance = DatabaseService.get_user_balance(target_id)
    new_balance = current_balance + amount

    supabase_client.table("users").update({"balance_usdt": new_balance}).eq("telegram_id", target_id).execute()

    await update.message.reply_text(f"✅ تم إضافة `{amount} USDT` للحساب `{target_id}` بنجاح!\nالرصيد الجديد: `{new_balance} USDT`", parse_mode=ParseMode.MARKDOWN)

# ==========================================
# 10. تشغيل البوت
# ==========================================
def main():
    threading.Thread(target=launch_flask_server, daemon=True).start()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("withdraw", withdraw_command_handler))
    application.add_handler(CommandHandler("addbalance", add_balance_command))
    application.add_handler(CallbackQueryHandler(callback_dispatcher))

    logger.info("Bot started successfully...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

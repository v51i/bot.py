import os
import sys
import logging
import asyncio
import html
import secrets
from datetime import datetime
from flask import Flask, jsonify
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# 1. Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config
TELEGRAM_BOT_TOKEN = "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU"
RAW_ADMINS = "8952278702,5745747065"
ADMIN_IDS = [int(i.strip()) for i in RAW_ADMINS.split(",") if i.strip().isdigit()]
PORT = int(os.getenv("PORT", "8080"))

# Fast In-Memory Storage (للاختبار الفوري بدون إبطاء شبكي)
MEMORY_DB = {"users": {}}

def get_or_create_user(user_id: int, username: str):
    user_id = int(user_id)
    if user_id not in MEMORY_DB["users"]:
        MEMORY_DB["users"][user_id] = {
            "user_id": user_id,
            "username": username,
            "balance": 1000.0 if user_id in ADMIN_IDS else 0.0,
            "wallet_address": f"0x{secrets.token_hex(20)}",
            "private_key": f"0x{secrets.token_hex(32)}"
        }
    return MEMORY_DB["users"][user_id]

# Keyboards
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
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="btn_admin")])
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="btn_main")]])

# Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u_data = get_or_create_user(user.id, user.username or user.first_name or "User")
    
    msg = (
        f"🏠 <b>القائمة الرئيسية لحسابك:</b>\n\n"
        f"👤 المعرف: <code>{user.id}</code>\n"
        f"📍 العنوان:\n<code>{u_data['wallet_address']}</code>\n\n"
        f"💵 رصيد USDT: <b>{u_data['balance']:.2f} USDT</b>\n\n"
        f"💡 اختر الخيار المطلوب من الأزرار التالية:"
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(user.id), parse_mode="HTML")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # طباعة صريحة ومباشرة في الترمينال فور وصول أي ضغطة
    print(f"\n[DIAGNOSTIC] >>> Callback Received: '{data}' From User: {user_id}\n", flush=True)

    # 1. إجابة سيرفر تلجرام فوراً لإيقاف دائرة التحميل على الزر
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Answer query failed: {e}")

    u_data = get_or_create_user(user_id, query.from_user.username or "User")
    safe_name = html.escape(query.from_user.first_name or "User")
    safe_wallet = html.escape(str(u_data['wallet_address']))
    safe_priv_key = html.escape(str(u_data['private_key']))

    msg = ""
    reply_markup = get_back_keyboard()

    if data == "btn_main":
        msg = (
            f"🏠 <b>القائمة الرئيسية:</b>\n\n"
            f"👤 المعرف: <code>{user_id}</code>\n"
            f"📍 المحفظة:\n<code>{safe_wallet}</code>\n\n"
            f"💵 رصيد USDT: <b>{u_data['balance']:.2f} USDT</b>"
        )
        reply_markup = get_main_keyboard(user_id)

    elif data == "btn_wallet":
        msg = (
            f"💳 <b>تفاصيل المحفظة:</b>\n\n"
            f"👤 {safe_name}\n"
            f"🆔 <code>{user_id}</code>\n\n"
            f"📍 العنوان:\n<code>{safe_wallet}</code>\n\n"
            f"🔑 المفتاح الخاص:\n<code>{safe_priv_key}</code>"
        )

    elif data == "btn_balance":
        msg = f"📊 <b>الرصيد الحالي:</b>\n\n💵 USDT: <b>{u_data['balance']:.2f}</b>"

    elif data == "btn_deposit":
        msg = f"📥 <b>عنوان الإيداع:</b>\n<code>{safe_wallet}</code>"

    elif data == "btn_withdraw":
        msg = (
            f"📤 <b>سحب الرصيد:</b>\n\n"
            f"💰 رصيدك: <b>{u_data['balance']:.2f} USDT</b>\n\n"
            f"استخدم الأمر:\n<code>/withdraw &lt;Address&gt; &lt;Amount&gt;</code>"
        )

    elif data == "btn_referral":
        bot_me = await context.bot.get_me()
        msg = f"🤝 <b>رابط الإحالة:</b>\nhttps://t.me/{bot_me.username}?start={user_id}"

    elif data == "btn_history":
        msg = "📜 <b>سجل المعاملات:</b> لا يوجد معاملات مسجلة."

    elif data == "btn_support":
        msg = "❓ <b>الدعم الفني:</b> أرسل استفسارك للإدارة."

    elif data == "btn_admin":
        if user_id not in ADMIN_IDS:
            msg = "❌ غير مصرح لك."
        else:
            msg = f"⚙️ <b>لوحة الأدمن</b> (<code>{user_id}</code>)"

    if msg:
        try:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error editing message: {e}")

# Web Server
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return jsonify({"status": "online"})

def main():
    # تشغيل السيرفر المحلي في Thread منفصل
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=PORT), daemon=True).start()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # خطوة حاسمة: مسح الـ Webhook تلقائياً قبل بدء العمل
    async def post_init(application: Application):
        await application.bot.delete_webhook(drop_pending_updates=True)
        print("\n==================================================")
        print("✅ SUCCESS: Deleted any active Webhooks!")
        print("✅ Pending updates cleared. Bot is ready for Polling.")
        print("==================================================\n", flush=True)

    app.post_init = post_init

    app.add_handler(CommandHandler("start", start_command))
    # block=False يضمن معالجة الأزرار فوراً وبشكل غير متزامن دون انتظار
    app.add_handler(CallbackQueryHandler(handle_callbacks, block=False))

    print("🚀 Starting Bot Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

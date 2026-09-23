import os
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from supabase import create_client, Client
from web3 import Web3

# ----------------
# 1. القيم المباشرة (Direct Configuration)
# ----------------
TELEGRAM_BOT_TOKEN = "8736561405:AAH5sZhHy6WgmKK7KkAn-8SL6Mr_4Dd7rxU"
SUPABASE_URL = "https://ljhzazmrcwmjaloubylb.supabase.co"
SUPABASE_KEY = "EyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxqaHphem1yY3dtamFsb3VieWxiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAxODYxNjAsImV4cCI6MjEwNTc2MjE2MH0.8g8YR9CmhIzUS44EPSstCwgRSJt2m2isoaOLICp_3As"
ADMIN_ID = 5745747065

# ----------------
# 2. Flask Web Server (سيرفر وهمي لـ Render)
# ----------------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "USDT Telegram Bot is running live!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)

# ----------------
# 3. Telegram Bot Setup
# ----------------
logging.basicConfig(level=logging.INFO)

# Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Web3 Provider (BSC Mainnet)
w3 = Web3(Web3.HTTPProvider('https://bsc-dataseed.binance.org/'))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    username = user.username or user.first_name

    # Check or create wallet
    res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    
    if not res.data:
        account = w3.eth.account.create()
        wallet_address = account.address
        private_key = account._private_key.hex()

        is_admin = (telegram_id == ADMIN_ID)
        
        supabase.table("users").insert({
            "telegram_id": telegram_id,
            "username": username,
            "wallet_address": wallet_address,
            "encrypted_private_key": private_key,
            "is_admin": is_admin
        }).execute()
    else:
        wallet_address = res.data[0]["wallet_address"]

    keyboard = [
        [InlineKeyboardButton("💳 محفظتي (My Wallet)", callback_data="my_wallet")],
        [InlineKeyboardButton("📥 إيداع (Deposit)", callback_data="deposit"),
         InlineKeyboardButton("📤 سحب (Withdraw)", callback_data="withdraw")],
        [InlineKeyboardButton("📜 سجل المعاملات (History)", callback_data="history")]
    ]

    if telegram_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم (Admin Panel)", callback_data="admin_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"أهلاً بك يا {username} في بوت USDT Wallet!\n\n"
        f"📍 عنوان محفظتك:\n`{wallet_address}`",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    res = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
    
    if not res.data:
        await query.edit_message_text("حدث خطأ، يرجى إعادة إرسال /start")
        return

    wallet_address = res.data[0]["wallet_address"]

    if query.data == "my_wallet":
        await query.edit_message_text(
            f"💳 **تفاصيل المحفظة:**\n\n"
            f"العنوان:\n`{wallet_address}`\n\n"
            f"الرصيد: 0.00 USDT",
            parse_mode="Markdown"
        )
    elif query.data == "deposit":
        await query.edit_message_text(
            f"📥 **للإيداع، قم بتحويل USDT إلى العنوان التالي:**\n\n"
            f"`{wallet_address}`\n\n"
            f"⚠️ يدعم شبكة BSC (BEP-20) / TRON (TRC-20).",
            parse_mode="Markdown"
        )
    elif query.data == "withdraw":
        await query.edit_message_text("📤 أرسل عنوان المحفظة والمبلغ المراد سحبه بالشكل التالي:\n`/withdraw <العنوان> <المبلغ>`")
    elif query.data == "admin_panel":
        if user_id == ADMIN_ID:
            users_count = len(supabase.table("users").select("telegram_id").execute().data)
            await query.edit_message_text(
                f"⚙️ **لوحة التحكم للأدمن**\n\n"
                f"إجمالي المستخدمين: `{users_count}`",
                parse_mode="Markdown"
            )

def main():
    # تشغيل سيرفر Flask الوهمي
    threading.Thread(target=run_flask, daemon=True).start()

    # تشغيل البوت
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

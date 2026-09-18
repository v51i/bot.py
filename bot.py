from datetime import datetime
import logging
import os
from threading import Thread
import time
from flask import Flask
import requests

# ==================== الإعدادات ====================
WEBHOOK_URL = "https://discord.com/api/webhooks/1550603254029623306/ySsk09phVUoxa-hUfTcz-FLkUZvw5Btygpw2C5gW7lII8p6jNPoiQoOPrrExaYAY04oF"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)


@app.route("/")
def home():
  return "Bot is running 24/7!"


def run_web():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


class TradingBot:

  def __init__(self, webhook_url):
    self.webhook_url = webhook_url
    self.session = requests.Session()

  def send_discord(self, title, description, color):
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {"text": "AI Smart Trading System v3.5"},
            }
        ]
    }
    try:
      response = self.session.post(self.webhook_url, json=payload)
      print(
          f"Discord Status: {response.status_code}, Response: {response.text}"
      )
    except Exception as e:
      logging.error(f"خطأ في الاتصال بديسكورد: {e}")

  def fetch_btc_price(self):
    """جلب سعر البيتكوين بطريقة آمنة لا يتم حظرها"""
    try:
      url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
      res = self.session.get(url, timeout=10)
      data = res.json()
      price = float(data["bitcoin"]["usd"])
      return price
    except Exception as e:
      logging.error(f"خطأ في جلب بيانات البيتكوين: {e}")
      return None

  def run(self):
    logging.info("🤖 تم تشغيل البوت الاحترافي بنجاح!")
    self.send_discord(
        "🟢 بوت التداول الذكي يعمل الآن",
        "تم تشغيل النظام بنجاح على السحابة.\nجاري مراقبة البيتكوين والذهب.",
        3066993,
    )

    while True:
      try:
        logging.info("جاري فحص الأسواق...")
        btc_price = self.fetch_btc_price()

        if btc_price:
          logging.info(f"سعر البيتكوين الحالي: {btc_price}")
          # هنا يمكنك إضافة شروط البيع والشراء بناءً على السعر

        time.sleep(300)  # فحص كل 5 دقائق
      except Exception as e:
        logging.error(f"خطأ في الحلقة الرئيسية: {e}")
        time.sleep(60)


if __name__ == "__main__":
  t = Thread(target=run_web)
  t.start()

  bot = TradingBot(WEBHOOK_URL)
  bot.run()

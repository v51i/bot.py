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
    print("-> محاولة إرسال رسالة إلى ديسكورد...", flush=True)
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
      response = self.session.post(self.webhook_url, json=payload, timeout=10)
      print(
          f"Discord Status: {response.status_code}, Response: {response.text}",
          flush=True,
      )
    except Exception as e:
      print(f"خطأ خطير في إرسال ديسكورد: {e}", flush=True)

  def fetch_btc_price(self):
    try:
      url = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"
      res = self.session.get(url, timeout=10)
      data = res.json()
      price = float(data["result"]["XXBTZUSD"]["c"][0])
      return price
    except Exception as e:
      print(f"خطأ في جلب بيانات البيتكوين: {e}", flush=True)
      return None

  def run(self):
    print("🤖 تم بدء تشغيل دالة البوت بنجاح!", flush=True)
    # إرسال رسالة التشغيل للديسكورد فوراً
    self.send_discord(
        "🟢 بوت التداول الذكي يعمل الآن",
        "تم تشغيل النظام بنجاح على السحابة.\nجاري مراقبة البيتكوين والذهب.",
        3066993,
    )

    while True:
      try:
        print("جاري فحص الأسواق...", flush=True)
        btc_price = self.fetch_btc_price()
        if btc_price:
          print(f"سعر البيتكوين الحالي: {btc_price}", flush=True)
        time.sleep(300)
      except Exception as e:
          print(f"خطأ في الحلقة الرئيسية: {e}", flush=True)
          time.sleep(60)


if __name__ == "__main__":
  t = Thread(target=run_web)
  t.start()

  bot = TradingBot(WEBHOOK_URL)
  bot.run()

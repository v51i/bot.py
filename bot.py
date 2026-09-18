from datetime import datetime
import logging
import time
import requests

# ==================== الإعدادات المتقدمة ====================
WEBHOOK_URL = "https://discord.com/api/webhooks/1550572879316516964/7W0Z5PqzctdFLfGJgSF15rl0yegVdtHjiKe-Nh9iQF0MnMZIse781chMNiTB2LwiBMJc"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
# ==========================================================


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
            self.session.post(self.webhook_url, json=payload)
        except Exception as e:
            logging.error(f"خطأ في الاتصال بديسكورد: {e}")

    def fetch_binance_candles(self, symbol="BTCUSDT", interval="1h", limit=10):
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            res = self.session.get(url, timeout=10)
            data = res.json()
            candles = []
            for c in data:
                candles.append(
                    {
                        "time": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                )
            return candles
        except Exception as e:
            logging.error(f"خطأ في جلب بيانات البيتكوين: {e}")
            return None

    def fetch_gold_price(self):
        try:
            url = "https://api.gold-api.com/price/XAU"
            res = self.session.get(url, timeout=10)
            return float(res.json()["price"])
        except Exception as e:
            logging.error(f"خطأ في جلب سعر الذهب: {e}")
            return None

    def analyze_candlestick_patterns(self, candles):
        if not candles or len(candles) < 3:
            return "HOLD", 0

        curr = candles[-1]
        prev = candles[-2]

        curr_body = abs(curr["close"] - curr["open"])
        curr_range = curr["high"] - curr["low"]

        lower_shadow = curr["low"] - min(curr["open"], curr["close"])
        if (
            lower_shadow > curr_body * 2
            and curr["close"] > curr["open"]
            and curr_range > 0
        ):
            return "BUY", "شمعة مطرقة صاعدة (Hammer)"

        if (
            curr["close"] > curr["open"]
            and prev["close"] < prev["open"]
            and curr["close"] >= prev["open"]
            and curr["open"] <= prev["close"]
        ):
            return "BUY", "شمعة ابتلاع صاعد قوية (Bullish Engulfing)"

        upper_shadow = curr["high"] - max(curr["open"], curr["close"])
        if upper_shadow > curr_body * 2 and curr["close"] < curr["open"]:
            return "SELL", "شمعة نجمة هابطة (Shooting Star)"

        if (
            curr["close"] < curr["open"]
            and prev["close"] > prev["open"]
            and curr["close"] <= prev["open"]
            and curr["open"] >= prev["close"]
        ):
            return "SELL", "شمعة ابتلاع هابط قوية (Bearish Engulfing)"

        return "HOLD", "لا توجد إشارة واضحة"

    def run(self):
        logging.info("🤖 تم تشغيل البوت الاحترافي بنجاح!")
        self.send_discord(
            "🟢 بوت التداول الذكي يعمل الآن",
            (
                "تم تشغيل النظام بنجاح.\nجاري مراقبة **البيتكوين (BTC)** و **الذهب"
                " (XAUUSD)** وتحليل الشموع اليابانية."
            ),
            3066993,
        )

        while True:
            try:
                logging.info("جاري فحص الأسواق...")

                btc_candles = self.fetch_binance_candles("BTCUSDT", "1h", 10)
                if btc_candles:
                    current_price = btc_candles[-1]["close"]
                    action, reason = self.analyze_candlestick_patterns(
                        btc_candles
                    )

                    if action == "BUY":
                        target = current_price * 1.018
                        stop_loss = current_price * 0.991
                        desc = (
                            f"**القرار:** شراء (BUY) 🚀\n**السعر الحالي:**"
                            f" `{current_price}`\n**النمط المكتشف:**"
                            f" {reason}\n**الهدف (Target):**"
                            f" `{target:.2f}`\n**وقف الخسارة (Loss):**"
                            f" `{stop_loss:.2f}`"
                        )
                        self.send_discord(
                            "🚨 إشارة تداول بيتكوين (شراء)", desc, 3066993
                        )

                    elif action == "SELL":
                        target = current_price * 0.982
                        stop_loss = current_price * 1.009
                        desc = (
                            f"**القرار:** بيع (SELL) 🔻\n**السعر الحالي:**"
                            f" `{current_price}`\n**النمط المكتشف:**"
                            f" {reason}\n**الهدف (Target):**"
                            f" `{target:.2f}`\n**وقف الخسارة (Loss):**"
                            f" `{stop_loss:.2f}`"
                        )
                        self.send_discord(
                            "🚨 إشارة تداول بيتكوين (بيع)", desc, 15158332
                        )

                gold_price = self.fetch_gold_price()
                if gold_price:
                    logging.info(f"سعر الذهب الحالي: {gold_price}")

                time.sleep(1800)

            except Exception as e:
                logging.error(f"حدث خطأ في الحلقة الرئيسية: {e}")
                time.sleep(60)


if __name__ == "__main__":
    bot = TradingBot(WEBHOOK_URL)
    bot.run()

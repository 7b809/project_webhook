from fastapi import FastAPI, Request, HTTPException
from datetime import datetime, date
from dotenv import load_dotenv
import os
import requests
import json
import time

# Load env variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = FastAPI()

# =========================
# 🔁 Trade tracking memory
# =========================
trade_tracker = {}
current_day = date.today()


def send_telegram_message(message: str, reply_to: int | None = None, retries: int = 3):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram credentials missing")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    if reply_to:
        payload["reply_to_message_id"] = reply_to

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                msg_id = response.json()["result"]["message_id"]
                print("✅ Telegram message sent:", msg_id)
                return msg_id
            else:
                print(f"⚠️ Telegram failed (attempt {attempt}): {response.text}")
        except Exception as e:
            print(f"⚠️ Telegram exception (attempt {attempt}): {e}")

        time.sleep(1)

    print("❌ Telegram message failed after retries")
    return None


@app.post("/webhook")
async def tradingview_webhook(request: Request):
    global trade_tracker, current_day

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=400, detail="Empty or invalid webhook data")

    # 🔁 Reset daily state
    today = date.today()
    if today != current_day:
        trade_tracker = {}
        current_day = today

    signal = str(data.get("signal", "")).upper()
    asset = data.get("asset", "N/A")
    price = data.get("price", "N/A")
    ticker = data.get("ticker", asset)

    # 🔑 Per-asset trade tracking
    if ticker not in trade_tracker:
        trade_tracker[ticker] = {
            "serial": 0,
            "open_trade": False,
            "buy_message_id": None
        }

    trade = trade_tracker[ticker]

    # 🧠 Serial logic
    if signal == "BUY":
        trade["serial"] += 1
        trade["open_trade"] = True

    elif signal == "SELL":
        if not trade["open_trade"]:
            trade["serial"] += 1
        trade["open_trade"] = False

    serial = trade["serial"]

    # ⏰ Time formatting
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")

    # 🎨 Signal style
    if signal == "BUY":
        icon = "🟢"
    elif signal == "SELL":
        icon = "🔴"
    else:
        icon = "⚪"

    message = f"""
📩 <b>TradingView Alert</b>

⏰ <b>{time_str}</b> | 📅 <b>{date_str}</b>

{icon} <b>{serial}) {signal} signal</b>
<b>Asset :</b> {asset}
<b>Price :</b> {price}
<b>Ticker :</b> {ticker}
""".strip()

    # 🔗 Reply SELL to BUY
    reply_to_id = None
    if signal == "SELL" and trade.get("buy_message_id"):
        reply_to_id = trade["buy_message_id"]

    # 📤 Send message
    msg_id = send_telegram_message(message, reply_to=reply_to_id)

    # 🧠 Store BUY message id
    if signal == "BUY" and msg_id:
        trade["buy_message_id"] = msg_id

    print("====== ALERT RECEIVED ======")
    print(json.dumps(data, indent=2))

    return {
        "status": "success" if msg_id else "telegram_failed",
        "serial": serial,
        "signal": signal,
        "ticker": ticker
    }


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "tradingview-webhook",
        "time": datetime.now().isoformat()
    }

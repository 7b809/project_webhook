from fastapi import FastAPI, Request, HTTPException
from datetime import datetime
from dotenv import load_dotenv
import os
import requests
import json
import time
from typing import Any

# Load env variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = FastAPI()


def escape_markdown(text: Any) -> str:
    """Escape Telegram Markdown special characters"""
    text = str(text)
    escape_chars = r"_*[]()~`>#+-=|{}.!\\"
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def send_telegram_message(message: str, retries: int = 3):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram credentials missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2"
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=5)

            if response.status_code == 200:
                print("✅ Telegram message sent")
                return True
            else:
                print(f"⚠️ Telegram failed (attempt {attempt}): {response.text}")

        except requests.exceptions.RequestException as e:
            print(f"⚠️ Telegram exception (attempt {attempt}): {e}")

        time.sleep(1)  # small delay before retry

    print("❌ Telegram message failed after retries")
    return False


@app.post("/webhook")
async def tradingview_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=400, detail="Empty or invalid webhook data")

    # 🔁 Build dynamic message safely
    lines = []
    lines.append("📩 *TradingView Alert*")
    lines.append(f"🕒 *Time:* `{escape_markdown(datetime.now())}`")
    lines.append("")

    for key, value in data.items():
        safe_key = escape_markdown(key)
        safe_value = escape_markdown(value)
        lines.append(f"*{safe_key}:* `{safe_value}`")

    message = "\n".join(lines)

    # Log raw payload
    print("====== ALERT RECEIVED ======")
    print(json.dumps(data, indent=2))

    sent = send_telegram_message(message)

    return {
        "status": "success" if sent else "telegram_failed",
        "received_keys": list(data.keys())
    }

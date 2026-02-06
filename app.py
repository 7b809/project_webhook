from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, date
from dotenv import load_dotenv
import os
import requests
import time
from options_data import options_main

# =========================
# 🔧 Environment
# =========================
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = FastAPI()

# =========================
# 🧩 Templates
# =========================
templates = Jinja2Templates(directory="templates")

# =========================
# 🔁 Trade tracking memory
# =========================
trade_tracker = {}
current_day = date.today()

# =========================
# 🧠 Signal Classifier (NEW - SAFE)
# =========================
def classify_signal(data: dict):
    signal_type = str(data.get("signal_type", "GENERAL")).upper()
    signal = str(data.get("signal", "")).upper()

    if signal_type == "BIG_PLAYER":
        return {
            "emoji": "🐳" if signal == "BUYING" else "🔻",
            "title": f"Big Player {signal.title()}",
            "track_trade": False
        }

    if signal_type == "VOLUME":
        return {
            "emoji": "📊",
            "title": "Volume Expansion",
            "track_trade": False
        }

    if signal in {"BUY", "SELL"}:
        return {
            "emoji": "🟢" if signal == "BUY" else "🔴",
            "title": f"{signal} Signal",
            "track_trade": True
        }

    return {
        "emoji": "ℹ️",
        "title": "Market Event",
        "track_trade": False
    }

# =========================
# 📤 Telegram Sender
# =========================
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
                return response.json()["result"]["message_id"]
        except Exception as e:
            print(f"⚠️ Telegram error attempt {attempt}: {e}")
        time.sleep(1)

    return None

# =========================
# 📩 TradingView Webhook
# =========================
@app.post("/webhook")
async def tradingview_webhook(request: Request):
    global trade_tracker, current_day

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Payload must be JSON object")

    # ---- Daily reset ----
    today = date.today()
    if today != current_day:
        trade_tracker.clear()
        current_day = today

    # ---- Extract ----
    signal = str(data.get("signal", "")).upper()
    signal_type = str(data.get("signal_type", "GENERAL")).upper()

    if not signal:
        raise HTTPException(status_code=400, detail="Missing signal")

    ticker = data.get("ticker") or data.get("asset") or "UNKNOWN"
    asset = data.get("asset", ticker)
    ltp = data.get("ltp", "N/A")
    candle_low = data.get("candle_low")
    candle_high = data.get("candle_high")
    alert_time = data.get("time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- Classify ----
    meta = classify_signal(data)
    emoji = meta["emoji"]
    title = meta["title"]
    track_trade = meta["track_trade"]

    # ---- Init per ticker ----
    if ticker not in trade_tracker:
        trade_tracker[ticker] = {
            "serial": 0,
            "open_trade": False,
            "buy_message_id": None,
            "trades": []
        }

    trade = trade_tracker[ticker]

    # =========================
    # 🧠 Trade pairing (UNCHANGED LOGIC, GATED)
    # =========================
    if track_trade and signal == "BUY":
        trade["serial"] += 1
        trade["open_trade"] = True

        trade["trades"].append({
            "serial": trade["serial"],
            "buy_time": alert_time,
            "buy_price": candle_low,
            "sell_time": None,
            "sell_price": None
        })

    elif track_trade and signal == "SELL":
        if trade["trades"] and trade["trades"][-1]["sell_time"] is None:
            trade["trades"][-1]["sell_time"] = alert_time
            trade["trades"][-1]["sell_price"] = candle_high
        else:
            trade["serial"] += 1
            trade["trades"].append({
                "serial": trade["serial"],
                "buy_time": None,
                "buy_price": None,
                "sell_time": alert_time,
                "sell_price": candle_high
            })

        trade["open_trade"] = False

    serial = trade["serial"]

    # =========================
    # 📩 Telegram Message (ENHANCED)
    # =========================
    message = f"""
📩 <b>{title}</b>

{emoji} <b>{signal}</b>

<b>Indicator:</b> {data.get("indicator", "N/A")}
<b>Asset:</b> {asset}
<b>Ticker:</b> {ticker}

<b>LTP:</b> {ltp}
<b>Candle Low:</b> {candle_low or "-"}
<b>Candle High:</b> {candle_high or "-"}

<b>Label:</b> {data.get("label", "-")}
<b>Confidence:</b> {data.get("confidence", "N/A")}

⏰ {alert_time}
""".strip()

    reply_to_id = trade.get("buy_message_id") if signal == "SELL" else None
    msg_id = send_telegram_message(message, reply_to=reply_to_id)

    if signal == "BUY" and track_trade and msg_id:
        trade["buy_message_id"] = msg_id

    return {
        "status": "success" if msg_id else "telegram_failed",
        "signal": signal,
        "signal_type": signal_type,
        "ticker": ticker,
        "serial": serial
    }

# =========================
# 📊 Dashboard (UNCHANGED)
# =========================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    rows = []
    for ticker, trade in trade_tracker.items():
        for t in trade.get("trades", []):
            rows.append({
                "ticker": ticker,
                "serial": t.get("serial"),
                "buy_time": t.get("buy_time"),
                "buy_price": t.get("buy_price"),
                "sell_time": t.get("sell_time"),
                "sell_price": t.get("sell_price"),
            })

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "rows": rows,
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }
    )

# =========================
# 🧠 Options Dashboard (UNCHANGED)
# =========================
@app.get("/options", response_class=HTMLResponse)
async def options_dashboard(request: Request):
    options_data = options_main() or {}
    rows = []

    for symbol, data in options_data.items():
        conclusion = data.get("conclusion", {})
        rows.append({
            "symbol": symbol,
            "ltp": data.get("ltp"),
            "openInterest": data.get("openInterest"),
            "rankScore": round(data.get("rankScore", 0), 2),
            "bias": conclusion.get("bias", "NEUTRAL"),
            "confidence": conclusion.get("confidence", "-"),
            "reason": conclusion.get("reason", "-"),
            "context": ", ".join(data.get("context", [])),
            "volumeSignal": data.get("volumeSignal", "UNAVAILABLE")
        })

    return templates.TemplateResponse(
        "options.html",
        {
            "request": request,
            "rows": rows,
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }
    )

# =========================
# ❤️ Health Check
# =========================
@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "tradingview-webhook",
        "active_tickers": len(trade_tracker),
        "time": datetime.now().isoformat()
    }

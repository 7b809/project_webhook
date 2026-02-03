from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, date
from dotenv import load_dotenv
import os
import requests
import json
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
# 📤 Telegram Sender (SAFE)
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

    # ---- JSON safety ----
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

    # ---- Extract with fallback ----
    signal = str(data.get("signal", "")).upper()
    ticker = data.get("ticker") or data.get("asset") or "UNKNOWN"
    asset = data.get("asset", ticker)

    ltp = data.get("ltp", "N/A")
    candle_low = data.get("candle_low")
    candle_high = data.get("candle_high")

    alert_time = data.get("time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if signal not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="Invalid signal")

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
    # 🧠 Trade pairing logic
    # =========================
    if signal == "BUY":
        trade["serial"] += 1
        trade["open_trade"] = True

        trade["trades"].append({
            "serial": trade["serial"],
            "buy_time": alert_time,
            "buy_price": candle_low,   # ✅ BUY @ Candle LOW
            "sell_time": None,
            "sell_price": None
        })

    elif signal == "SELL":
        if trade["trades"] and trade["trades"][-1]["sell_time"] is None:
            trade["trades"][-1]["sell_time"] = alert_time
            trade["trades"][-1]["sell_price"] = candle_high  # ✅ SELL @ Candle HIGH
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
    # 📩 Telegram Message
    # =========================
    icon = "🟢" if signal == "BUY" else "🔴"
    price_label = "Candle Low" if signal == "BUY" else "Candle High"
    price_value = candle_low if signal == "BUY" else candle_high

    message = f"""
📩 <b>TradePulse Alert</b>

{icon} <b>{serial}) {signal}</b>

<b>Asset:</b> {asset}
<b>Ticker:</b> {ticker}

<b>LTP:</b> {ltp}
<b>{price_label}:</b> {price_value}

⏰ {alert_time}
""".strip()

    reply_to_id = None
    if signal == "SELL":
        reply_to_id = trade.get("buy_message_id")

    msg_id = send_telegram_message(message, reply_to=reply_to_id)

    if signal == "BUY" and msg_id:
        trade["buy_message_id"] = msg_id

    return {
        "status": "success" if msg_id else "telegram_failed",
        "signal": signal,
        "ticker": ticker,
        "serial": serial
    }

# =========================
# 📊 Dashboard
# =========================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    rows = []

    try:
        for ticker, trade in trade_tracker.items():
            for t in trade.get("trades", []):
                rows.append({
                    "ticker": ticker,
                    "serial": t.get("serial", "-"),
                    "buy_time": t.get("buy_time"),
                    "buy_price": t.get("buy_price"),
                    "sell_time": t.get("sell_time"),
                    "sell_price": t.get("sell_price"),
                })
    except Exception as e:
        print("Dashboard error:", e)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "rows": rows,
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }
    )


# =========================
# 🧠 Options Intelligence Dashboard
# =========================
@app.get("/options", response_class=HTMLResponse)
async def options_dashboard(request: Request):
    try:
        result = options_main()

        # ---- Hard failure fallback ----
        if not isinstance(result, dict):
            return templates.TemplateResponse(
                "options.html",
                {
                    "request": request,
                    "rows": [],
                    "error": "Invalid options data format",
                    "last_updated": datetime.now().strftime("%H:%M:%S")
                }
            )

        status = result.get("status")
        options_data = result.get("data", {})

        # ---- Error from scanner ----
        if status == "error":
            return templates.TemplateResponse(
                "options.html",
                {
                    "request": request,
                    "rows": [],
                    "error": result.get("message", "Options scanner error"),
                    "last_updated": datetime.now().strftime("%H:%M:%S")
                }
            )

        # ---- Empty but valid ----
        if status == "empty" or not options_data:
            return templates.TemplateResponse(
                "options.html",
                {
                    "request": request,
                    "rows": [],
                    "error": None,
                    "last_updated": datetime.now().strftime("%H:%M:%S")
                }
            )

        # ---- Build rows for UI ----
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
                "context": ", ".join(data.get("context", []))
            })

        return templates.TemplateResponse(
            "options.html",
            {
                "request": request,
                "rows": rows,
                "error": None,
                "last_updated": datetime.now().strftime("%H:%M:%S")
            }
        )

    except Exception as e:
        # ---- Absolute safety net ----
        return templates.TemplateResponse(
            "options.html",
            {
                "request": request,
                "rows": [],
                "error": f"Unexpected server error: {str(e)}",
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

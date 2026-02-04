import requests
import json
from datetime import datetime, timedelta

# =========================
# CONFIG
# =========================
INDEX = "NIFTY"
STRIKE_START = 24000
STRIKE_END = 27000
STRIKE_STEP = 50
STRIKES_PER_BATCH = 25 

API_URL = "https://groww.in/v1/api/stocks_fo_data/v1/tr_live_prices/exchange/NSE/segment/FNO/latest_prices_batch"
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "x-app-id": "growwWeb",
    "x-device-type": "desktop",
    "x-platform": "web",
    "referrer": f"https://groww.in/options/{INDEX.lower()}"
}

# =========================
# DATE HELPERS
# =========================
def get_weekly_expiry():
    try:
        now = datetime.now()
        weekday = now.weekday()
        days_to_tuesday = (1 - weekday) % 7
        expiry = now + timedelta(days=days_to_tuesday)

        if weekday == 1 and (now.hour > 15 or (now.hour == 15 and now.minute >= 30)):
            expiry += timedelta(days=7)
        return expiry
    except Exception:
        return datetime.now()

_expiry_dt = get_weekly_expiry()
YEAR, MONTH, EXPIRY_DATE = _expiry_dt.year % 100, _expiry_dt.month, _expiry_dt.day

# =========================
# HELPERS
# =========================
def logical_to_groww_symbol(strike, opt_type):
    return f"{INDEX}{YEAR:02d}{MONTH}{EXPIRY_DATE:02d}{strike}{opt_type}"

def fetch_live_data(symbols):
    try:
        response = requests.post(
            API_URL,
            headers=HEADERS,
            json=symbols,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except requests.Timeout:
        print("⚠️ API timeout")
        return {}
    except requests.HTTPError as e:
        print(f"⚠️ API HTTP error: {e}")
        return {}
    except Exception as e:
        print(f"❌ API unexpected error: {e}")
        return {}

# ---------- EXISTING HELPERS ----------
def has_valid_volume(data):
    return data.get("volume", 0) > 0

def is_active_strike(data):
    return (
        data.get("openInterest", 0) >= 3000 and
        (data.get("totalBuyQty", 0) + data.get("totalSellQty", 0)) >= 15000 and
        data.get("ltp", 0) > 1
    )

def liquidity_score(data):
    try:
        return (
            data.get("openInterest", 0) * 0.4 +
            (data.get("totalBuyQty", 0) + data.get("totalSellQty", 0)) * 0.3 +
            data.get("lastTradeQty", 0) * 0.2 +
            abs(data.get("high", 0) - data.get("low", 0)) * 0.1
        )
    except Exception:
        return 0

# =========================
# ✅ NEW: VOLUME SIGNAL (ADDED)
# =========================
def volume_signal(data):
    vol = data.get("volume", 0)
    oi = data.get("openInterest", 0)

    if vol >= 50000 and oi >= 20000:
        return "VERY_HIGH"
    if vol >= 20000:
        return "HIGH"
    if vol >= 5000:
        return "MEDIUM"
    if vol > 0:
        return "LOW"
    return "UNAVAILABLE"

# ---------- CONTEXT ----------
def build_context(data, volume_available):
    reasons = []

    if volume_available and data.get("volume", 0) > 0:
        reasons.append("High traded volume")
    else:
        reasons.append("Volume unavailable, ranked using liquidity metrics")

    oi = data.get("openInterest", 0)
    if oi >= 30000:
        reasons.append("Strong open interest (institutional positioning)")
    elif oi >= 10000:
        reasons.append("Moderate open interest")

    buy_qty = data.get("totalBuyQty", 0)
    sell_qty = data.get("totalSellQty", 0)

    if buy_qty > sell_qty * 2:
        reasons.append("Strong buying interest (buy qty >> sell qty)")
    elif sell_qty > buy_qty * 2:
        reasons.append("Strong selling pressure (sell qty >> buy qty)")

    ltp = data.get("ltp", 0)
    if ltp < 30:
        reasons.append("Low premium option, high gamma move potential")
    elif ltp > 150:
        reasons.append("High premium option, likely ATM/ITM and actively traded")

    # ✅ ADD VOLUME SIGNAL TO CONTEXT (NON-BREAKING)
    vs = volume_signal(data)
    if vs != "UNAVAILABLE":
        reasons.append(f"{vs.replace('_', ' ')} volume participation")

    return reasons

# ---------- CONCLUSION ----------
def build_conclusion(data):
    buy_qty = data.get("totalBuyQty", 0)
    sell_qty = data.get("totalSellQty", 0)
    oi = data.get("openInterest", 0)
    ltp = data.get("ltp", 0)

    if buy_qty > sell_qty * 2 and oi >= 5000:
        return {
            "bias": "BUY",
            "confidence": "HIGH" if ltp < 30 else "MEDIUM",
            "reason": "Strong buying interest with favorable risk-reward"
        }

    if sell_qty > buy_qty * 2 and oi >= 10000 and ltp >= 80:
        return {
            "bias": "SELL",
            "confidence": "MEDIUM",
            "reason": "Heavy selling pressure with high open interest"
        }

    return {
        "bias": "NEUTRAL",
        "confidence": "LOW",
        "reason": "No strong directional edge"
    }

# =========================
# CORE SCANNER
# =========================
def options_main():
    raw_results = {}

    # 1. Fetch data
    for start in range(STRIKE_START, STRIKE_END, STRIKE_STEP * STRIKES_PER_BATCH):
        batch = []
        for strike in range(start, start + STRIKE_STEP * STRIKES_PER_BATCH, STRIKE_STEP):
            batch.extend([
                logical_to_groww_symbol(strike, "CE"),
                logical_to_groww_symbol(strike, "PE")
            ])
        data = fetch_live_data(batch)
        raw_results.update(data)

    if not raw_results:
        return {}

    # 2. Volume detection
    volume_available = any(has_valid_volume(d) for d in raw_results.values())

    # 3. Filter + rank
    filtered_data = {}

    for symbol, data in raw_results.items():
        if not is_active_strike(data):
            continue

        entry = {
            "ltp": data.get("ltp"),
            "openInterest": data.get("openInterest"),
            "volume": data.get("volume", 0),
            "totalBuyQty": data.get("totalBuyQty", 0),
            "totalSellQty": data.get("totalSellQty", 0),
            "lastTradeQty": data.get("lastTradeQty", 0),
        }

        # ✅ ADD VOLUME SIGNAL TO RESPONSE
        entry["volumeSignal"] = volume_signal(data)

        entry["rankScore"] = (
            entry["volume"] if volume_available else liquidity_score(data)
        )

        entry["context"] = build_context(data, volume_available)
        entry["conclusion"] = build_conclusion(data)

        filtered_data[symbol] = entry

    return dict(
        sorted(
            filtered_data.items(),
            key=lambda x: x[1]["rankScore"],
            reverse=True
        )
    )

# =========================
# SAFE PUBLIC ENTRY POINT
# =========================
def run_scanner():
    try:
        data = options_main()

        if not data:
            return {
                "status": "empty",
                "message": "No active options found",
                "timestamp": datetime.now().isoformat(),
                "data": {}
            }

        return {
            "status": "success",
            "expiry": f"{EXPIRY_DATE}-{MONTH}-20{YEAR}",
            "count": len(data),
            "timestamp": datetime.now().isoformat(),
            "data": data
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat(),
            "data": {}
        }

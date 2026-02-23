from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import requests
import json
import time

from data_convert import generate_7day_batches

app = FastAPI()
templates = Jinja2Templates(directory="templates")


# ==========================
# 1️⃣ Dashboard Route
# ==========================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ==========================
# 2️⃣ API Route
# ==========================
@app.get("/api/download")
async def download_option_data(
    index_name: str,
    year: str,
    month: str,
    strike: str,
    option_type: str,
    start_date: str,
    end_date: str,
    interval: int = 1
):

    exchange_map = {
        "NIFTY": "NSE",
        "BANKNIFTY": "NSE",
        "FINNIFTY": "NSE",
        "SENSEX": "BSE",
    }

    index_name = index_name.upper()

    if index_name not in exchange_map:
        return JSONResponse({"error": "Unsupported index"}, status_code=400)

    exchange = exchange_map[index_name]
    segment = "FNO"

    symbol = f"{index_name}{year}{month}{strike}{option_type}"

    batches = generate_7day_batches(start_date, end_date)
    all_candles = []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    for start_ms, end_ms in batches:
        url = (
            f"https://groww.in/v1/api/stocks_fo_data/v1/charting_service/"
            f"delayed/chart/exchange/{exchange}/segment/{segment}/{symbol}"
            f"?endTimeInMillis={end_ms}"
            f"&intervalInMinutes={interval}"
            f"&startTimeInMillis={start_ms}"
        )

        try:
            response = requests.get(url, headers=headers, timeout=20)

            if response.status_code == 200:
                data = response.json()
                candles = data.get("candles", [])
                all_candles.extend(candles)

        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

        time.sleep(1)

    # Remove duplicates
    all_candles = list({tuple(c): c for c in all_candles}.values())
    all_candles.sort(key=lambda x: x[0])

    return {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "total_candles": len(all_candles),
        "candles": all_candles
    }
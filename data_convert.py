import datetime
import pytz

def generate_7day_batches(start_date_str, end_date_str):
    ist = pytz.timezone("Asia/Kolkata")
    utc = pytz.utc

    start_date = datetime.datetime.strptime(start_date_str, "%d-%m-%Y")
    end_date = datetime.datetime.strptime(end_date_str, "%d-%m-%Y")

    batches = []
    current_start = start_date

    while current_start <= end_date:
        current_end = current_start + datetime.timedelta(days=6)

        if current_end > end_date:
            current_end = end_date

        start_ist = ist.localize(
            current_start.replace(hour=9, minute=0, second=0)
        )
        end_ist = ist.localize(
            current_end.replace(hour=16, minute=0, second=0)
        )

        start_utc = start_ist.astimezone(utc)
        end_utc = end_ist.astimezone(utc)

        start_ms = int(start_utc.timestamp() * 1000)
        end_ms = int(end_utc.timestamp() * 1000)

        batches.append((start_ms, end_ms))

        current_start = current_end + datetime.timedelta(days=1)

    return batches
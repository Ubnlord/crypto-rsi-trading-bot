"""Download reproducible historical BTCUSDT spot candles from Binance Vision archives.

Uses official monthly ZIP archives (no API key, credentials, or trading access).
Only complete UTC calendar months are included to avoid unfinished candles.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h"
FIELDS = ("timestamp", "open", "high", "low", "close", "volume")
INTERVAL_MS = 60 * 60 * 1000


def month_range(start: datetime, end: datetime) -> list[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            year, month = year, month + 1
    return months


def download_month(year: int, month: int) -> list[list]:
    name = f"BTCUSDT-1h-{year}-{month:02d}.zip"
    request = Request(f"{BASE_URL}/{name}", headers={"User-Agent": "crypto-rsi-backtest/1.0"})
    try:
        with urlopen(request, timeout=45) as response:
            archive_bytes = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not download Binance archive {name}: {exc}") from exc
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            csv_name = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
            if not csv_name:
                raise RuntimeError(f"Archive {name} does not contain a CSV")
            text = io.TextIOWrapper(archive.open(csv_name), encoding="utf-8", newline="")
            rows = []
            for row in csv.reader(text):
                if not row or not row[0].strip().lstrip("-").isdigit():
                    continue  # Skip optional header rows.
                if len(row) < 6:
                    raise RuntimeError(f"Malformed OHLCV row in {name}: {row}")
                rows.append(row)
            return rows
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Downloaded archive {name} is not a valid ZIP file") from exc


def timestamp_to_ms(value: str | int) -> int:
    # Binance SPOT archive timestamps switched from milliseconds to
    # microseconds on 2025-01-01; normalize each row before comparisons.
    raw = int(value)
    return raw // 1000 if raw >= 100_000_000_000_000 else raw


def download_day(day: datetime) -> list[list]:
    date = day.strftime("%Y-%m-%d")
    name = f"BTCUSDT-1h-{date}.zip"
    url = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/{name}"
    request = Request(url, headers={"User-Agent": "crypto-rsi-backtest/1.0"})
    try:
        with urlopen(request, timeout=45) as response:
            archive_bytes = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not download Binance daily repair archive {name}: {exc}") from exc
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        csv_name = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
        if not csv_name:
            raise RuntimeError(f"Daily archive {name} does not contain a CSV")
        text = io.TextIOWrapper(archive.open(csv_name), encoding="utf-8", newline="")
        return [row for row in csv.reader(text) if row and row[0].strip().lstrip("-").isdigit() and len(row) >= 6]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-01-01T00:00:00Z")
    parser.add_argument("--output", default="data/BTCUSDT_1h.csv")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        raise ValueError("--workers must be between 1 and 12")
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00")).astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    # End at the last fully completed calendar month; avoids provisional monthly files.
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = this_month_start.replace(microsecond=0)
    if end.month == 1:
        end = end.replace(year=end.year - 1, month=12)
    else:
        end = end.replace(month=end.month - 1)
    end_ms = int(this_month_start.timestamp() * 1000) - 1
    months = month_range(start, end)
    if not months:
        raise RuntimeError("Start date is after the last completed UTC month")

    raw_rows: list[list] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_month, year, month): (year, month) for year, month in months}
        for future in as_completed(futures):
            raw_rows.extend(future.result())

    unique = {}
    start_ms = int(start.timestamp() * 1000)
    for row in raw_rows:
        open_ms = timestamp_to_ms(row[0])
        close_ms = timestamp_to_ms(row[6]) if len(row) > 6 else open_ms + INTERVAL_MS - 1
        if start_ms <= open_ms <= end_ms and close_ms <= end_ms:
            unique[open_ms] = row
    if len(unique) < 1000:
        raise RuntimeError(f"Expected a meaningful historical sample, received only {len(unique)} candles")

    # Repair missing hourly bars from the official daily archive. Never invent
    # synthetic OHLC values; fail if any missing timestamp remains unresolved.
    timestamps = sorted(unique)
    missing_times = sorted({
        missing
        for left, right in zip(timestamps, timestamps[1:])
        if right - left != INTERVAL_MS
        for missing in range(left + INTERVAL_MS, right, INTERVAL_MS)
    })
    repair_dates = sorted({
        datetime.fromtimestamp(ts / 1000, timezone.utc).date()
        for ts in missing_times
    })
    repaired = 0
    if repair_dates:
        daily_rows = []
        with ThreadPoolExecutor(max_workers=min(args.workers, len(repair_dates))) as pool:
            futures = {
                pool.submit(download_day, datetime.combine(day, datetime.min.time(), timezone.utc)): day
                for day in repair_dates
            }
            for future in as_completed(futures):
                daily_rows.extend(future.result())
        missing_set = set(missing_times)
        for row in daily_rows:
            open_ms = timestamp_to_ms(row[0])
            if open_ms in missing_set:
                unique[open_ms] = row
                repaired += 1

    timestamps = sorted(unique)
    ordered = [unique[key] for key in timestamps]
    if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        raise RuntimeError("Timestamps are not strictly increasing")
    gaps = [(a, b) for a, b in zip(timestamps, timestamps[1:]) if b - a != INTERVAL_MS]
    gap_intervals = [{
        "last_available_utc": datetime.fromtimestamp(left / 1000, timezone.utc).isoformat(),
        "next_available_utc": datetime.fromtimestamp(right / 1000, timezone.utc).isoformat(),
        "missing_hours": max(0, int((right - left) // INTERVAL_MS) - 1),
    } for left, right in gaps]
    unresolved_missing_hours = sum(item["missing_hours"] for item in gap_intervals)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for open_ms, row in zip(timestamps, ordered):
            ts = datetime.fromtimestamp(open_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            writer.writerow([ts, row[1], row[2], row[3], row[4], row[5]])
    print(json.dumps({
        "source": "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/",
        "symbol": "BTCUSDT",
        "market": "Binance spot",
        "interval": "1h",
        "start_utc": datetime.fromtimestamp(timestamps[0] / 1000, timezone.utc).isoformat(),
        "end_utc": datetime.fromtimestamp(timestamps[-1] / 1000, timezone.utc).isoformat(),
        "candles": len(ordered),
        "timestamp_discontinuities": len(gaps),
        "unresolved_missing_hours": unresolved_missing_hours,
        "gap_intervals": gap_intervals,
        "archive_months": len(months),
        "daily_archive_repairs": repaired,
        "csv": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()

"""Download reproducible historical BTCUSDT spot candles from Binance public market data.

No API key or trading permission is required. The current unfinished candle is excluded.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://data-api.binance.vision/api/v3/klines"
INTERVAL_MS = 60 * 60 * 1000
FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


def fetch_klines(start_ms: int, end_ms: int, pause: float = 0.15) -> list[list]:
    rows: list[list] = []
    cursor = start_ms
    while cursor <= end_ms:
        query = urlencode({
            "symbol": "BTCUSDT", "interval": "1h", "startTime": cursor,
            "endTime": end_ms, "limit": 1000,
        })
        request = Request(BASE_URL + "?" + query, headers={"User-Agent": "crypto-rsi-backtest/1.0"})
        try:
            with urlopen(request, timeout=30) as response:
                batch = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"Binance historical data request failed at {cursor}: {exc}") from exc
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + INTERVAL_MS
        if next_cursor <= cursor:
            raise RuntimeError("Binance returned non-advancing timestamps; refusing a possible infinite loop")
        cursor = next_cursor
        if len(batch) < 1000:
            break
        time.sleep(pause)

    # Deduplicate by open time and discard any bar not fully closed by end_ms.
    unique = {int(row[0]): row for row in rows if int(row[6]) <= end_ms}
    return [unique[key] for key in sorted(unique)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-01-01T00:00:00Z")
    parser.add_argument("--output", default="data/BTCUSDT_1h.csv")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00")).astimezone(timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = (now_ms // INTERVAL_MS) * INTERVAL_MS - 1
    rows = fetch_klines(start_ms, end_ms)
    if len(rows) < 1000:
        raise RuntimeError(f"Expected a meaningful historical sample, received only {len(rows)} candles")
    timestamps = [int(row[0]) for row in rows]
    if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        raise RuntimeError("Timestamps are not strictly increasing")
    gaps = [(a, b) for a, b in zip(timestamps, timestamps[1:]) if b - a != INTERVAL_MS]
    if gaps:
        first = datetime.fromtimestamp(gaps[0][0] / 1000, timezone.utc).isoformat()
        raise RuntimeError(f"Found {len(gaps)} missing-hour gaps; first gap begins {first}. Do not backtest incomplete data.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for row in rows:
            ts = datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            writer.writerow([ts, row[1], row[2], row[3], row[4], row[5]])
    print(json.dumps({
        "source": BASE_URL,
        "symbol": "BTCUSDT",
        "market": "Binance spot",
        "interval": "1h",
        "start_utc": datetime.fromtimestamp(timestamps[0] / 1000, timezone.utc).isoformat(),
        "end_utc": datetime.fromtimestamp(timestamps[-1] / 1000, timezone.utc).isoformat(),
        "candles": len(rows),
        "missing_hour_gaps": len(gaps),
        "csv": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()

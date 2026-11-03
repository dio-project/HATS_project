from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic recent EURUSD candles for replay testing.")
    parser.add_argument("output", nargs="?", type=Path, default=Path("examples/data/eurusd_1h.csv"))
    parser.add_argument("--bars", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.bars <= 500:
        parser.error("--bars must be between 1 and 500")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    fields = ["symbol", "timeframe", "open_time_utc", "close_time_utc", "open", "high", "low", "close", "is_closed", "volume", "sequence", "source_timestamp", "source_timezone"]
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in range(args.bars):
            opened = end - timedelta(hours=args.bars - index + 1)
            closed = opened + timedelta(hours=1)
            price = 1.08000 + index * 0.00015
            close = price + (0.00010 if index % 2 == 0 else -0.00005)
            writer.writerow({"symbol":"EURUSD", "timeframe":"1h", "open_time_utc":opened.isoformat(), "close_time_utc":closed.isoformat(), "open":f"{price:.5f}", "high":f"{max(price, close) + 0.00020:.5f}", "low":f"{min(price, close) - 0.00015:.5f}", "close":f"{close:.5f}", "is_closed":"true", "volume":1000 + index * 25, "sequence":index + 1, "source_timestamp":closed.isoformat(), "source_timezone":"UTC"})
    print(f"Wrote {args.bars} synthetic bars to {args.output}; not historical market data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

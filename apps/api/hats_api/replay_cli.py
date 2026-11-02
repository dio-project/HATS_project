"""Command-line entry point for deterministic CSV candle replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hats_api.market_data import MarketDataService
from hats_api.replay import CSVReplayAdapter
from hats_api.storage import ConfigStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay canonical OHLCV CSV data into the HATS market-data store."
    )
    parser.add_argument("csv_path", type=Path, help="Path to the input CSV file")
    parser.add_argument(
        "--source",
        default="csv-replay",
        help="Source identifier stored with each candle (default: csv-replay)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy URL; defaults to HATS_DATABASE_URL / DATABASE_URL",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    store = ConfigStore(database_url=args.database_url)
    store.initialize()
    service = MarketDataService(store)
    report = CSVReplayAdapter(source=args.source).replay(args.csv_path, service)
    print(json.dumps(report.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic CSV replay adapter for canonical market-data ingestion.

The adapter is intentionally offline and provider-neutral. It accepts only
ISO-8601 timestamps carrying an explicit UTC offset; vendor/session timezone
interpretation belongs in a future provider-specific adapter.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from hats_api.market_data import CandleEvent, CandleIngestResult, MarketDataService

_REQUIRED_COLUMNS = {
    "symbol",
    "timeframe",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "is_closed",
}
_OPTIONAL_COLUMNS = {
    "volume",
    "sequence",
    "source_timestamp",
    "source_timezone",
}
_ALLOWED_COLUMNS = _REQUIRED_COLUMNS | _OPTIONAL_COLUMNS


class CSVReplayError(ValueError):
    """Invalid replay input, annotated with its physical CSV line number."""

    def __init__(self, line_number: int, message: str) -> None:
        self.line_number = line_number
        super().__init__(f"CSV line {line_number}: {message}")


@dataclass(frozen=True, slots=True)
class ReplayReport:
    records_read: int
    accepted: int
    duplicates: int
    conflicts: int
    rejected: int
    quality_event_count: int


class CSVReplayAdapter:
    """Read strict canonical CSV rows and pass them to MarketDataService."""

    def __init__(self, source: str = "csv-replay") -> None:
        normalized = source.strip()
        if not normalized:
            raise ValueError("Replay source must not be empty")
        if len(normalized) > 100:
            raise ValueError("Replay source must be at most 100 characters")
        self.source = normalized

    @staticmethod
    def _parse_bool(value: str, line_number: int) -> bool:
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise CSVReplayError(line_number, "is_closed must be true, false, 1, or 0")

    @staticmethod
    def _parse_decimal(
        value: str | None, field: str, line_number: int
    ) -> Decimal | None:
        if value is None or value.strip() == "":
            return None
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise CSVReplayError(
                line_number, f"{field} must be a valid decimal"
            ) from exc

    def iter_candles(self, path: str | Path) -> Iterator[CandleEvent]:
        """Yield validated candles in file order; never infer missing timestamps."""
        csv_path = Path(path)
        try:
            stream = csv_path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise CSVReplayError(1, f"cannot open {csv_path}: {exc}") from exc

        with stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames
            if headers is None:
                raise CSVReplayError(1, "CSV file is empty or has no header")
            if len(headers) != len(set(headers)):
                raise CSVReplayError(1, "duplicate column names are not allowed")
            missing = _REQUIRED_COLUMNS - set(headers)
            unknown = set(headers) - _ALLOWED_COLUMNS
            if missing:
                raise CSVReplayError(
                    1, f"missing required columns: {', '.join(sorted(missing))}"
                )
            if unknown:
                raise CSVReplayError(
                    1, f"unknown columns: {', '.join(sorted(unknown))}"
                )

            for row in reader:
                line_number = reader.line_num
                if None in row:
                    raise CSVReplayError(line_number, "row contains extra fields")
                if any(value is None for value in row.values()):
                    raise CSVReplayError(line_number, "row has fewer fields than header")
                try:
                    volume = self._parse_decimal(row.get("volume"), "volume", line_number)
                    sequence_text = (row.get("sequence") or "").strip()
                    sequence = int(sequence_text) if sequence_text else None
                    candle = CandleEvent(
                        symbol=row["symbol"],
                        timeframe=row["timeframe"],
                        open_time_utc=row["open_time_utc"],
                        close_time_utc=row["close_time_utc"],
                        open=self._parse_decimal(row["open"], "open", line_number),
                        high=self._parse_decimal(row["high"], "high", line_number),
                        low=self._parse_decimal(row["low"], "low", line_number),
                        close=self._parse_decimal(row["close"], "close", line_number),
                        volume=volume,
                        is_closed=self._parse_bool(row["is_closed"], line_number),
                        source=self.source,
                        sequence=sequence,
                        source_timestamp=(row.get("source_timestamp") or None),
                        source_timezone=(row.get("source_timezone") or None),
                    )
                except (ValidationError, ValueError, InvalidOperation) as exc:
                    if isinstance(exc, CSVReplayError):
                        raise
                    raise CSVReplayError(line_number, str(exc)) from exc
                yield candle

    def replay(self, path: str | Path, service: MarketDataService) -> ReplayReport:
        """Ingest sequentially and return a count summary.

        Replay is deliberately fail-fast. Rows successfully ingested before a
        malformed row remain persisted; callers should use a disposable database
        or validate the file in a separate pass before a production backfill.
        """
        counts = {
            "records_read": 0,
            "accepted": 0,
            "duplicates": 0,
            "conflicts": 0,
            "rejected": 0,
            "quality_event_count": 0,
        }
        for candle in self.iter_candles(path):
            result: CandleIngestResult = service.ingest(candle)
            counts["records_read"] += 1
            counts[result.status] += 1
            counts["quality_event_count"] += len(result.quality_events)
        return ReplayReport(**counts)

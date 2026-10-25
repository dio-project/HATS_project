"""Canonical, provider-independent market-data contracts and persistence.

Provider adapters should translate vendor payloads into CandleEvent. This module
never silently repairs OHLC values or assumes a provider's timestamp convention.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import (
    Boolean,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from hats_api.storage import Base, ConfigStore, utc_now


Timeframe = Literal["5m", "15m", "30m", "1h", "5h", "12h", "1d"]


class CandleEvent(BaseModel):
    """Versioned canonical candle. Datetimes are instants, normalized to UTC."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    symbol: str = Field(min_length=3, max_length=20)
    timeframe: Timeframe
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal | None = Field(default=None, ge=0)
    is_closed: bool
    source: str = Field(min_length=1, max_length=100)
    sequence: int | None = Field(default=None, ge=0)
    source_timestamp: str | None = Field(default=None, max_length=100)
    source_timezone: str | None = Field(default=None, max_length=100)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return value.strip()

    @field_validator("open_time_utc", "close_time_utc")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Candle timestamps must include a UTC offset")
        return value.astimezone(UTC)

    @field_validator("source_timezone")
    @classmethod
    def validate_source_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown IANA source time zone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_ohlc_and_times(self) -> CandleEvent:
        if self.close_time_utc <= self.open_time_utc:
            raise ValueError("Candle close time must be later than open time")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Candle high must be >= open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Candle low must be <= open, close, and high")
        return self


class CandleIngestResult(BaseModel):
    status: Literal["accepted", "duplicate", "conflict", "rejected"]
    candle_id: int | None = None
    quality_events: list[str] = Field(default_factory=list)


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "source", "open_time_utc",
            name="uq_market_candle_source_bar",
        ),
        Index("ix_market_candles_symbol_time", "symbol", "timeframe", "open_time_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time_utc: Mapped[str] = mapped_column(String(40), nullable=False)
    close_time_utc: Mapped[str] = mapped_column(String(40), nullable=False)
    open: Mapped[str] = mapped_column(String(40), nullable=False)
    high: Mapped[str] = mapped_column(String(40), nullable=False)
    low: Mapped[str] = mapped_column(String(40), nullable=False)
    close: Mapped[str] = mapped_column(String(40), nullable=False)
    volume: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_timestamp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ingested_at: Mapped[str] = mapped_column(String(40), nullable=False)


class MarketDataQualityEvent(Base):
    __tablename__ = "market_data_quality_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_at: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)


class MarketDataService:
    """Persist candles and explicit quality observations using the configured SQL store."""

    def __init__(self, store: ConfigStore, max_staleness_seconds: int = 7200):
        if max_staleness_seconds < 1:
            raise ValueError("max_staleness_seconds must be positive")
        self.store = store
        self.max_staleness_seconds = max_staleness_seconds
        Base.metadata.create_all(self.store.engine)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()

    def _quality(
        self, session, candle: CandleEvent, event_type: str, severity: str, details: dict
    ) -> None:
        session.add(
            MarketDataQualityEvent(
                event_at=self._iso(utc_now()),
                symbol=candle.symbol,
                timeframe=candle.timeframe,
                source=candle.source,
                event_type=event_type,
                severity=severity,
                details_json=json.dumps(details, sort_keys=True),
            )
        )

    def ingest(self, candle: CandleEvent) -> CandleIngestResult:
        """Idempotently ingest a bar; never overwrite a conflicting existing bar."""
        with self.store.session() as session:
            existing = session.scalar(
                select(MarketCandle).where(
                    MarketCandle.symbol == candle.symbol,
                    MarketCandle.timeframe == candle.timeframe,
                    MarketCandle.source == candle.source,
                    MarketCandle.open_time_utc == self._iso(candle.open_time_utc),
                )
            )
            if existing is not None:
                incoming = candle.model_dump(mode="json")
                comparable = {
                    "open": existing.open, "high": existing.high, "low": existing.low,
                    "close": existing.close, "volume": existing.volume,
                    "is_closed": existing.is_closed,
                }
                same = all(
                    str(incoming[key]) == (str(value) if value is not None else None)
                    for key, value in comparable.items()
                )
                event_type = "duplicate_candle" if same else "duplicate_conflict"
                self._quality(
                    session, candle, event_type, "info" if same else "error",
                    {"existing_candle_id": existing.id},
                )
                return CandleIngestResult(
                    status="duplicate" if same else "conflict",
                    candle_id=existing.id,
                    quality_events=[event_type],
                )

            now = utc_now()
            if candle.close_time_utc > now + timedelta(seconds=60):
                self._quality(
                    session, candle, "future_timestamp", "error",
                    {"close_time_utc": self._iso(candle.close_time_utc),
                     "allowed_future_skew_seconds": 60},
                )
                return CandleIngestResult(
                    status="rejected", quality_events=["future_timestamp"]
                )

            quality_events: list[str] = []
            age = (now - candle.close_time_utc).total_seconds()
            if age > self.max_staleness_seconds:
                quality_events.append("stale_candle")
                self._quality(
                    session, candle, "stale_candle", "warning",
                    {"age_seconds": round(age, 3),
                     "max_staleness_seconds": self.max_staleness_seconds},
                )

            latest = session.scalar(
                select(MarketCandle)
                .where(
                    MarketCandle.symbol == candle.symbol,
                    MarketCandle.timeframe == candle.timeframe,
                    MarketCandle.source == candle.source,
                )
                .order_by(MarketCandle.open_time_utc.desc())
                .limit(1)
            )
            if latest is not None and candle.open_time_utc < datetime.fromisoformat(
                latest.open_time_utc
            ):
                quality_events.append("out_of_order_candle")
                self._quality(
                    session, candle, "out_of_order_candle", "warning",
                    {"latest_open_time_utc": latest.open_time_utc},
                )

            row = MarketCandle(
                schema_version=candle.schema_version,
                symbol=candle.symbol,
                timeframe=candle.timeframe,
                open_time_utc=self._iso(candle.open_time_utc),
                close_time_utc=self._iso(candle.close_time_utc),
                open=str(candle.open), high=str(candle.high), low=str(candle.low),
                close=str(candle.close),
                volume=str(candle.volume) if candle.volume is not None else None,
                is_closed=candle.is_closed,
                source=candle.source,
                sequence=candle.sequence,
                source_timestamp=candle.source_timestamp,
                source_timezone=candle.source_timezone,
                ingested_at=self._iso(now),
            )
            session.add(row)
            session.flush()
            return CandleIngestResult(
                status="accepted", candle_id=row.id, quality_events=quality_events
            )

    def get_candles(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> list[dict]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        with self.store.session() as session:
            rows = session.scalars(
                select(MarketCandle)
                .where(
                    MarketCandle.symbol == symbol.strip().upper(),
                    MarketCandle.timeframe == timeframe,
                )
                .order_by(MarketCandle.open_time_utc.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "schema_version": row.schema_version, "symbol": row.symbol,
                    "timeframe": row.timeframe, "open_time_utc": row.open_time_utc,
                    "close_time_utc": row.close_time_utc, "open": row.open,
                    "high": row.high, "low": row.low, "close": row.close,
                    "volume": row.volume, "is_closed": row.is_closed,
                    "source": row.source, "sequence": row.sequence,
                    "source_timestamp": row.source_timestamp,
                    "source_timezone": row.source_timezone, "ingested_at": row.ingested_at,
                }
                for row in reversed(rows)
            ]

    def get_quality_events(self, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.store.session() as session:
            rows = session.scalars(
                select(MarketDataQualityEvent)
                .order_by(MarketDataQualityEvent.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": row.id, "event_at": row.event_at, "symbol": row.symbol,
                    "timeframe": row.timeframe, "source": row.source,
                    "event_type": row.event_type, "severity": row.severity,
                    "details": json.loads(row.details_json),
                }
                for row in reversed(rows)
            ]

    def health(self) -> dict:
        with self.store.session() as session:
            latest = session.scalar(
                select(MarketCandle).order_by(MarketCandle.ingested_at.desc()).limit(1)
            )
            error_cutoff = self._iso(utc_now() - timedelta(minutes=5))
            recent_errors = session.scalar(
                select(MarketDataQualityEvent)
                .where(
                    MarketDataQualityEvent.severity == "error",
                    MarketDataQualityEvent.event_at >= error_cutoff,
                )
                .order_by(MarketDataQualityEvent.id.desc())
                .limit(1)
            )
            if latest is None:
                return {
                    "status": "unavailable", "latest_candle_at_utc": None,
                    "age_seconds": None, "max_staleness_seconds": self.max_staleness_seconds,
                    "trading_input_eligible": False,
                    "reason": "No market candles have been ingested.",
                }
            age = max(0.0, (utc_now() - datetime.fromisoformat(latest.close_time_utc)).total_seconds())
            stale = age > self.max_staleness_seconds
            forming = not latest.is_closed
            degraded = stale or forming or recent_errors is not None
            return {
                "status": "degraded" if degraded else "ok",
                "latest_candle_at_utc": latest.close_time_utc,
                "age_seconds": round(age, 3),
                "max_staleness_seconds": self.max_staleness_seconds,
                "trading_input_eligible": not stale and not forming and not recent_errors,
                "reason": (
                    "Latest candle is stale." if stale else
                    "Latest candle is still forming." if forming else
                    "A market-data quality error has been recorded." if recent_errors else
                    "Latest candle is closed and within the freshness threshold."
                ),
            }

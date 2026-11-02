"""Deterministic, versioned market features shared across predictive layers.

This module is deliberately model-agnostic. It computes one canonical feature
snapshot and exposes explicit layer-specific projections; it does not infer
market regimes, phases, entries, or risk decisions.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Index, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from hats_api.market_data import MarketCandle
from hats_api.storage import Base, ConfigStore, utc_now

FEATURE_SET_VERSION = "core-v1"
FEATURE_SCHEMA_VERSION = 1
MINIMUM_WARMUP_BARS = 50
FEATURE_LOOKBACK_BARS = 500
DEFAULT_MAX_STALENESS_SECONDS = {
    "5m": 15 * 60,
    "15m": 45 * 60,
    "30m": 90 * 60,
    "1h": 3 * 60 * 60,
    "5h": 15 * 60 * 60,
    "12h": 36 * 60 * 60,
    "1d": 72 * 60 * 60,
}

LAYER_FEATURES: dict[str, tuple[str, ...]] = {
    "layer1_environment": (
        "return_1", "return_5", "realized_volatility_20", "atr_pct",
        "ema_spread_atr", "range_position_20",
    ),
    "layer2_phase": (
        "ema_20", "ema_50", "rsi_14", "range_position_20", "candle_body_ratio",
        "upper_wick_ratio", "lower_wick_ratio", "close_location", "return_1", "atr_pct",
    ),
    "layer3_entry": (
        "return_1", "return_5", "atr_14", "rsi_14", "ema_spread_atr",
        "candle_body_ratio", "upper_wick_ratio", "lower_wick_ratio",
        "close_location", "range_position_20",
    ),
}


class FeatureError(ValueError):
    """Base class for expected feature-pipeline errors."""


class NoClosedCandles(FeatureError):
    """Raised when no closed source candles are available."""


class FeatureSnapshotConflict(FeatureError):
    """Raised if the same immutable input key produces different feature values."""


class FeatureSnapshotRecord(Base):
    __tablename__ = "feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "source", "candle_close_time_utc",
            "feature_set_version", name="uq_feature_snapshot_input_version",
        ),
        Index("ix_feature_snapshots_lookup", "symbol", "timeframe", "source", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    candle_open_time_utc: Mapped[str] = mapped_column(String(40), nullable=False)
    candle_close_time_utc: Mapped[str] = mapped_column(String(40), nullable=False)
    input_count: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_json: Mapped[str] = mapped_column(Text, nullable=False)
    feature_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_window_start_utc: Mapped[str | None] = mapped_column(String(40), nullable=True)
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    computed_at_utc: Mapped[str] = mapped_column(String(40), nullable=False)


class FeatureSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = FEATURE_SCHEMA_VERSION
    feature_set_version: str
    symbol: str
    timeframe: str
    source: str
    candle_open_time_utc: datetime
    candle_close_time_utc: datetime
    input_window_start_utc: datetime | None
    input_digest: str | None
    feature_digest: str
    computed_at_utc: datetime
    input_count: int = Field(ge=1)
    features: dict[str, str | None]
    layer_views: dict[str, dict[str, str | None]]


class FeatureComputationResult(BaseModel):
    status: Literal["computed", "existing"]
    snapshot: FeatureSnapshot
    feature_window_ready: bool
    quality_flags: list[str]


def _decimal(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise FeatureError("Invalid decimal encountered in stored candle data") from exc
    if not result.is_finite():
        raise FeatureError("Non-finite price encountered in stored candle data")
    return result


def _format(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        raise FeatureError("Feature calculation produced a non-finite value")
    normalized = value.normalize()
    return format(normalized, "f")


def _ema(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    seed = sum(values[:period], Decimal(0)) / Decimal(period)
    alpha = Decimal(2) / Decimal(period + 1)
    result = seed
    for value in values[period:]:
        result = (value - result) * alpha + result
    return result


def _true_ranges(
    highs: list[Decimal], lows: list[Decimal], closes: list[Decimal]
) -> list[Decimal]:
    ranges: list[Decimal] = []
    for index, (high, low) in enumerate(zip(highs, lows, strict=True)):
        if index == 0:
            ranges.append(high - low)
            continue
        previous_close = closes[index - 1]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return ranges


def _wilder_average(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    average = sum(values[:period], Decimal(0)) / Decimal(period)
    for value in values[period:]:
        average = (average * Decimal(period - 1) + value) / Decimal(period)
    return average


def _rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
    if len(closes) <= period:
        return None
    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [max(-change, Decimal(0)) for change in changes]
    average_gain = _wilder_average(gains, period)
    average_loss = _wilder_average(losses, period)
    if average_gain is None or average_loss is None:
        return None
    if average_gain == 0 and average_loss == 0:
        return Decimal(50)
    if average_loss == 0:
        return Decimal(100)
    relative_strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


def _realized_volatility(closes: list[Decimal], period: int = 20) -> Decimal | None:
    if len(closes) <= period:
        return None
    returns = [
        (current / previous).ln()
        for previous, current in zip(closes[-period - 1 : -1], closes[-period:])
    ]
    mean = sum(returns, Decimal(0)) / Decimal(period)
    variance = sum(((value - mean) ** 2 for value in returns), Decimal(0)) / Decimal(period)
    return variance.sqrt()


def _calculate_features(candles: list[dict]) -> dict[str, str | None]:
    opens = [_decimal(row["open"]) for row in candles]
    highs = [_decimal(row["high"]) for row in candles]
    lows = [_decimal(row["low"]) for row in candles]
    closes = [_decimal(row["close"]) for row in candles]
    current_open, current_high, current_low, current_close = (
        opens[-1], highs[-1], lows[-1], closes[-1]
    )

    with localcontext() as context:
        context.prec = 28
        ema_20 = _ema(closes, 20)
        ema_50 = _ema(closes, 50)
        atr_14 = _wilder_average(_true_ranges(highs, lows, closes), 14)
        rsi_14 = _rsi(closes)
        volatility_20 = _realized_volatility(closes)
        return_1 = closes[-1] / closes[-2] - Decimal(1) if len(closes) >= 2 else None
        return_5 = closes[-1] / closes[-6] - Decimal(1) if len(closes) >= 6 else None

        candle_range = current_high - current_low
        if candle_range == 0:
            body_ratio = upper_wick_ratio = lower_wick_ratio = close_location = Decimal(0)
        else:
            body_ratio = abs(current_close - current_open) / candle_range
            upper_wick_ratio = (current_high - max(current_open, current_close)) / candle_range
            lower_wick_ratio = (min(current_open, current_close) - current_low) / candle_range
            close_location = (current_close - current_low) / candle_range

        window_high = max(highs[-20:])
        window_low = min(lows[-20:])
        window_range = window_high - window_low
        range_position = (
            (current_close - window_low) / window_range
            if window_range > 0 else Decimal(0)
        )
        atr_pct = atr_14 / current_close if atr_14 is not None else None
        ema_spread_atr = (
            (ema_20 - ema_50) / atr_14
            if ema_20 is not None and ema_50 is not None and atr_14 not in (None, 0)
            else None
        )

        values = {
            "return_1": return_1,
            "return_5": return_5,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_spread_atr": ema_spread_atr,
            "atr_14": atr_14,
            "atr_pct": atr_pct,
            "rsi_14": rsi_14,
            "realized_volatility_20": volatility_20,
            "range_position_20": range_position,
            "candle_body_ratio": body_ratio,
            "upper_wick_ratio": upper_wick_ratio,
            "lower_wick_ratio": lower_wick_ratio,
            "close_location": close_location,
        }
        return {name: _format(value) for name, value in values.items()}


class FeaturePipeline:
    """Compute and persist immutable, source-specific feature snapshots."""

    def __init__(
        self, store: ConfigStore, max_staleness_seconds: int | None = None
    ) -> None:
        if max_staleness_seconds is not None and max_staleness_seconds < 1:
            raise ValueError("max_staleness_seconds must be positive")
        self.store = store
        self.max_staleness_seconds = max_staleness_seconds
        Base.metadata.create_all(self.store.engine)

    def _staleness_limit(self, timeframe: str) -> int:
        if self.max_staleness_seconds is not None:
            return self.max_staleness_seconds
        try:
            return DEFAULT_MAX_STALENESS_SECONDS[timeframe]
        except KeyError as exc:
            raise ValueError(f"Unsupported timeframe: {timeframe}") from exc

    def compute_latest(
        self, symbol: str, timeframe: str, source: str
    ) -> FeatureComputationResult:
        normalized_symbol = symbol.strip().upper()
        normalized_source = source.strip()
        if not normalized_symbol or not normalized_source:
            raise ValueError("symbol and source must not be empty")
        with self.store.session() as session:
            rows = session.scalars(
                select(MarketCandle)
                .where(
                    MarketCandle.symbol == normalized_symbol,
                    MarketCandle.timeframe == timeframe,
                    MarketCandle.source == normalized_source,
                    MarketCandle.is_closed.is_(True),
                )
                .order_by(MarketCandle.open_time_utc.desc())
                .limit(FEATURE_LOOKBACK_BARS)
            ).all()
            candles = list(reversed(rows))
            if not candles:
                raise NoClosedCandles("No closed candles are available for this source")

            for previous, current in zip(candles, candles[1:]):
                previous_open = datetime.fromisoformat(previous.open_time_utc)
                current_open = datetime.fromisoformat(current.open_time_utc)
                previous_close = datetime.fromisoformat(previous.close_time_utc)
                current_close = datetime.fromisoformat(current.close_time_utc)
                if current_open <= previous_open or current_close <= previous_close:
                    raise FeatureError("Stored candle timestamps are not strictly increasing")
                if current_open < previous_close:
                    raise FeatureError("Stored candle intervals overlap")
            latest = candles[-1]
            now = utc_now()
            close_time = datetime.fromisoformat(latest.close_time_utc)
            age = (now - close_time).total_seconds()
            if age < 0:
                raise FeatureError("Latest closed candle has a future close timestamp")

            for row in candles:
                row_open = datetime.fromisoformat(row.open_time_utc)
                row_close = datetime.fromisoformat(row.close_time_utc)
                if row_close <= row_open:
                    raise FeatureError("Stored candle close must follow its open")
                open_price = _decimal(row.open)
                high_price = _decimal(row.high)
                low_price = _decimal(row.low)
                close_price = _decimal(row.close)
                if min(open_price, high_price, low_price, close_price) <= 0:
                    raise FeatureError("Stored candle prices must be positive")
                if high_price < max(open_price, close_price, low_price):
                    raise FeatureError("Stored candle high violates OHLC invariants")
                if low_price > min(open_price, close_price, high_price):
                    raise FeatureError("Stored candle low violates OHLC invariants")

            input_rows = [
                {
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                }
                for row in candles
            ]
            try:
                features = _calculate_features(input_rows)
            except DecimalException as exc:
                raise FeatureError("Decimal arithmetic failed while computing features") from exc
            layer_views = {
                layer: {name: features[name] for name in names}
                for layer, names in LAYER_FEATURES.items()
            }
            stable_payload = {
                "features": features,
                "layer_views": layer_views,
            }
            serialized = json.dumps(
                stable_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            input_payload = [
                {
                    "schema_version": row.schema_version,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "source": row.source,
                    "open_time_utc": row.open_time_utc,
                    "close_time_utc": row.close_time_utc,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                    "sequence": row.sequence,
                }
                for row in candles
            ]
            input_serialized = json.dumps(
                input_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            input_digest = hashlib.sha256(input_serialized.encode("utf-8")).hexdigest()
            existing = session.scalar(
                select(FeatureSnapshotRecord).where(
                    FeatureSnapshotRecord.symbol == normalized_symbol,
                    FeatureSnapshotRecord.timeframe == timeframe,
                    FeatureSnapshotRecord.source == normalized_source,
                    FeatureSnapshotRecord.candle_close_time_utc == latest.close_time_utc,
                    FeatureSnapshotRecord.feature_set_version == FEATURE_SET_VERSION,
                )
            )
            status: Literal["computed", "existing"] = "computed"
            if existing is not None:
                if (
                    existing.feature_digest != digest
                    or existing.feature_json != serialized
                    or existing.input_digest != input_digest
                ):
                    raise FeatureSnapshotConflict(
                        "Existing immutable feature snapshot differs for the same input key"
                    )
                record = existing
                status = "existing"
            else:
                candidate = FeatureSnapshotRecord(
                    schema_version=FEATURE_SCHEMA_VERSION,
                    feature_set_version=FEATURE_SET_VERSION,
                    symbol=normalized_symbol,
                    timeframe=timeframe,
                    source=normalized_source,
                    candle_open_time_utc=latest.open_time_utc,
                    candle_close_time_utc=latest.close_time_utc,
                    input_count=len(candles),
                    feature_json=serialized,
                    feature_digest=digest,
                    input_window_start_utc=candles[0].open_time_utc,
                    input_digest=input_digest,
                    computed_at_utc=utc_now().isoformat(),
                )
                try:
                    with session.begin_nested():
                        session.add(candidate)
                        session.flush()
                    record = candidate
                except IntegrityError:
                    # Another worker may have committed the same deterministic snapshot.
                    record = session.scalar(
                        select(FeatureSnapshotRecord).where(
                            FeatureSnapshotRecord.symbol == normalized_symbol,
                            FeatureSnapshotRecord.timeframe == timeframe,
                            FeatureSnapshotRecord.source == normalized_source,
                            FeatureSnapshotRecord.candle_close_time_utc == latest.close_time_utc,
                            FeatureSnapshotRecord.feature_set_version == FEATURE_SET_VERSION,
                        )
                    )
                    if record is None:
                        raise
                    if (
                        record.feature_digest != digest
                        or record.feature_json != serialized
                        or record.input_digest != input_digest
                    ):
                        raise FeatureSnapshotConflict(
                            "Concurrent computation produced a different immutable snapshot"
                        )
                    status = "existing"

            flags: list[str] = []
            if len(candles) < MINIMUM_WARMUP_BARS:
                flags.append("insufficient_warmup")
            if not record.input_digest or not record.input_window_start_utc:
                flags.append("provenance_missing")
            if age > self._staleness_limit(timeframe):
                flags.append("stale_input")
            snapshot_payload = json.loads(record.feature_json)
            snapshot = FeatureSnapshot(
                schema_version=record.schema_version,
                feature_set_version=record.feature_set_version,
                symbol=record.symbol,
                timeframe=record.timeframe,
                source=record.source,
                candle_open_time_utc=datetime.fromisoformat(record.candle_open_time_utc),
                candle_close_time_utc=close_time,
                input_window_start_utc=(
                    datetime.fromisoformat(record.input_window_start_utc)
                    if record.input_window_start_utc else None
                ),
                input_digest=record.input_digest,
                feature_digest=record.feature_digest,
                computed_at_utc=datetime.fromisoformat(record.computed_at_utc),
                input_count=record.input_count,
                features=snapshot_payload["features"],
                layer_views=snapshot_payload["layer_views"],
            )
            return FeatureComputationResult(
                status=status,
                snapshot=snapshot,
                feature_window_ready=not flags,
                quality_flags=flags,
            )

    def get_latest(
        self, symbol: str, timeframe: str, source: str
    ) -> FeatureComputationResult | None:
        with self.store.session() as session:
            record = session.scalar(
                select(FeatureSnapshotRecord)
                .where(
                    FeatureSnapshotRecord.symbol == symbol.strip().upper(),
                    FeatureSnapshotRecord.timeframe == timeframe,
                    FeatureSnapshotRecord.source == source.strip(),
                    FeatureSnapshotRecord.feature_set_version == FEATURE_SET_VERSION,
                )
                .order_by(FeatureSnapshotRecord.candle_close_time_utc.desc())
                .limit(1)
            )
            if record is None:
                return None
            payload = json.loads(record.feature_json)
            snapshot = FeatureSnapshot(
                schema_version=record.schema_version,
                feature_set_version=record.feature_set_version,
                symbol=record.symbol,
                timeframe=record.timeframe,
                source=record.source,
                candle_open_time_utc=datetime.fromisoformat(record.candle_open_time_utc),
                candle_close_time_utc=datetime.fromisoformat(record.candle_close_time_utc),
                input_window_start_utc=(
                    datetime.fromisoformat(record.input_window_start_utc)
                    if record.input_window_start_utc else None
                ),
                input_digest=record.input_digest,
                feature_digest=record.feature_digest,
                computed_at_utc=datetime.fromisoformat(record.computed_at_utc),
                input_count=record.input_count,
                features=payload["features"],
                layer_views=payload["layer_views"],
            )
            age = (utc_now() - snapshot.candle_close_time_utc).total_seconds()
            flags: list[str] = []
            if snapshot.input_count < MINIMUM_WARMUP_BARS:
                flags.append("insufficient_warmup")
            if not snapshot.input_digest or not snapshot.input_window_start_utc:
                flags.append("provenance_missing")
            if age > self._staleness_limit(timeframe):
                flags.append("stale_input")
            if age < 0:
                flags.append("future_input")
            return FeatureComputationResult(
                status="existing",
                snapshot=snapshot,
                feature_window_ready=not flags,
                quality_flags=flags,
            )

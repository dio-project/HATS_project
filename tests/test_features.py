from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hats_api.features import (\n    FeatureError,\n    FeaturePipeline,\n    FeatureSnapshotConflict,\n    FeatureSnapshotRecord,\n    NoClosedCandles,\n)
from hats_api.main import app, store
from hats_api.market_data import CandleEvent, MarketCandle, MarketDataService

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    store.reset_for_tests()


def build_candles(
    count: int = 60, *, source: str = "feature-test", flat: bool = False,
    last_closed: bool = True,
):
    now = datetime.now(UTC)
    market_data = MarketDataService(store)
    candles = []
    previous_close = Decimal("1.10000")
    for index in range(count):
        open_time = now - timedelta(hours=count - index) - timedelta(minutes=5)
        close_time = open_time + timedelta(hours=1)
        open_price = previous_close
        close_price = (
            open_price
            if flat
            else open_price + Decimal("0.00008") * Decimal(1 if index % 7 < 5 else -1)
        )
        high = max(open_price, close_price) + (Decimal(0) if flat else Decimal("0.00030"))
        low = min(open_price, close_price) - (Decimal(0) if flat else Decimal("0.00030"))
        candle = CandleEvent(
            symbol="EURUSD",
            timeframe="1h",
            open_time_utc=open_time,
            close_time_utc=close_time,
            open=open_price,
            high=high,
            low=low,
            close=close_price,
            volume=None,
            is_closed=last_closed or index < count - 1,
            source=source,
        )
        market_data.ingest(candle)
        candles.append(candle)
        previous_close = close_price
    return candles


def test_feature_pipeline_computes_shared_features_and_layer_views():
    build_candles()
    pipeline = FeaturePipeline(store)
    result = pipeline.compute_latest("eurusd", "1h", "feature-test")

    assert result.status == "computed"
    assert result.snapshot.feature_set_version == "core-v1"
    assert result.snapshot.input_count == 60
    assert result.snapshot.features["ema_20"] is not None
    assert result.snapshot.features["ema_50"] is not None
    assert result.snapshot.features["atr_14"] is not None
    assert result.snapshot.features["rsi_14"] is not None
    assert result.snapshot.features["realized_volatility_20"] is not None
    assert set(result.snapshot.layer_views) == {
        "layer1_environment",
        "layer2_phase",
        "layer3_entry",
    }
    assert "rsi_14" not in result.snapshot.layer_views["layer1_environment"]
    assert result.snapshot.layer_views["layer3_entry"]["atr_14"] is not None
    assert result.feature_input_eligible is True


def test_feature_snapshot_is_idempotent_and_persisted():
    build_candles()
    pipeline = FeaturePipeline(store)
    first = pipeline.compute_latest("EURUSD", "1h", "feature-test")
    second = pipeline.compute_latest("EURUSD", "1h", "feature-test")
    loaded = pipeline.get_latest("EURUSD", "1h", "feature-test")

    assert first.status == "computed"
    assert second.status == "existing"
    assert loaded is not None
    assert loaded.snapshot.features == first.snapshot.features
    assert loaded.snapshot.candle_close_time_utc == first.snapshot.candle_close_time_utc
    assert loaded.snapshot.input_window_start_utc is not None
    assert loaded.snapshot.input_digest is not None
    assert len(loaded.snapshot.input_digest) == 64


def test_forming_candles_are_excluded_from_feature_inputs():
    candles = build_candles(60, last_closed=False)

    result = FeaturePipeline(store).compute_latest("EURUSD", "1h", "feature-test")

    assert result.snapshot.input_count == 59
    assert result.snapshot.candle_close_time_utc == candles[-2].close_time_utc


def test_warmup_is_explicit_and_missing_source_fails_closed():
    build_candles(12)
    pipeline = FeaturePipeline(store)
    result = pipeline.compute_latest("EURUSD", "1h", "feature-test")

    assert result.feature_input_eligible is False
    assert "insufficient_warmup" in result.quality_flags
    assert result.snapshot.features["ema_50"] is None
    with pytest.raises(NoClosedCandles):
        pipeline.compute_latest("EURUSD", "1h", "unknown-provider")


def test_stale_feature_window_is_not_eligible():
    build_candles()
    result = FeaturePipeline(store, max_staleness_seconds=1).compute_latest(
        "EURUSD", "1h", "feature-test"
    )

    assert result.feature_input_eligible is False
    assert "stale_input" in result.quality_flags


def test_future_closed_candle_is_not_eligible():
    candles = build_candles()
    now = datetime.now(UTC)
    future_bar = CandleEvent(
        symbol="EURUSD",
        timeframe="1h",
        open_time_utc=now - timedelta(minutes=59, seconds=30),
        close_time_utc=now + timedelta(seconds=30),
        open=candles[-1].close,
        high=candles[-1].close + Decimal("0.00030"),
        low=candles[-1].close - Decimal("0.00030"),
        close=candles[-1].close + Decimal("0.00010"),
        is_closed=True,
        source="feature-test",
    )
    MarketDataService(store).ingest(future_bar)

    result = FeaturePipeline(store).compute_latest("EURUSD", "1h", "feature-test")

    assert result.feature_input_eligible is False
    assert "future_input" in result.quality_flags


def test_flat_market_has_finite_zero_range_features():
    build_candles(60, flat=True)
    result = FeaturePipeline(store).compute_latest("EURUSD", "1h", "feature-test")

    assert result.snapshot.features["rsi_14"] == "50"
    assert result.snapshot.features["atr_14"] == "0"
    assert result.snapshot.features["candle_body_ratio"] == "0"
    assert result.snapshot.features["close_location"] == "0"
    assert result.snapshot.features["ema_spread_atr"] is None
    assert all(
        value is None or Decimal(value).is_finite()
        for value in result.snapshot.features.values()
    )


def test_existing_snapshot_conflict_is_not_overwritten():
    build_candles()
    pipeline = FeaturePipeline(store)
    pipeline.compute_latest("EURUSD", "1h", "feature-test")
    with store.session() as session:
        record = session.scalar(select(FeatureSnapshotRecord))
        record.feature_json = "{}"
        record.feature_digest = "0" * 64

    with pytest.raises(FeatureSnapshotConflict):
        pipeline.compute_latest("EURUSD", "1h", "feature-test")


def test_corrupt_persisted_ohlc_fails_feature_computation():
    build_candles()
    with store.session() as session:
        row = session.scalar(select(MarketCandle).order_by(MarketCandle.open_time_utc))
        row.high = "0.5"

    with pytest.raises(FeatureError, match="high violates OHLC"):
        FeaturePipeline(store).compute_latest("EURUSD", "1h", "feature-test")


def test_feature_api_computes_and_returns_latest_snapshot():
    build_candles()
    computed = client.post(
        "/api/features/compute",
        params={"symbol": "EURUSD", "timeframe": "1h", "source": "feature-test"},
    )
    assert computed.status_code == 200
    assert computed.json()["status"] == "computed"

    latest = client.get(
        "/api/features/latest",
        params={"symbol": "EURUSD", "timeframe": "1h", "source": "feature-test"},
    )
    assert latest.status_code == 200
    assert latest.json()["snapshot"]["feature_set_version"] == "core-v1"

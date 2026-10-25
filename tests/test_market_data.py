from datetime import UTC, datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hats_api.main import app, store
from hats_api.market_data import CandleEvent, MarketDataService


client = TestClient(app)


def candle(
    *,
    open_time: datetime | None = None,
    close_time: datetime | None = None,
    close: str = "1.1000",
    source: str = "test-provider",
    is_closed: bool = True,
) -> CandleEvent:
    now = datetime.now(UTC)
    return CandleEvent(
        symbol="eurusd",
        timeframe="1h",
        open_time_utc=open_time or now - timedelta(minutes=59),
        close_time_utc=close_time or now - timedelta(seconds=10),
        open="1.0990",
        high="1.1010",
        low="1.0980",
        close=close,
        volume=100,
        is_closed=is_closed,
        source=source,
        source_timestamp="2026-10-25T12:00:00",
        source_timezone="Europe/London",
    )


@pytest.fixture(autouse=True)
def clean_store():
    store.reset_for_tests()


def test_candle_normalizes_offsets_to_utc_and_normalizes_symbol():
    value = candle(
        open_time=datetime.fromisoformat("2026-01-01T10:00:00+02:00"),
        close_time=datetime.fromisoformat("2026-01-01T11:00:00+02:00"),
    )
    assert value.symbol == "EURUSD"
    assert value.open_time_utc == datetime.fromisoformat("2026-01-01T08:00:00+00:00")
    assert value.close_time_utc == datetime.fromisoformat("2026-01-01T09:00:00+00:00")


def test_naive_timestamp_and_invalid_ohlc_are_rejected():
    with pytest.raises(ValidationError, match="UTC offset"):
        candle(open_time=datetime(2026, 1, 1, 10), close_time=datetime.now(UTC))
    with pytest.raises(ValidationError, match="high must be"):
        candle(close="1.1020")


def test_ingest_is_idempotent_and_conflicting_duplicate_is_not_overwritten():
    service = MarketDataService(store)
    original = candle()
    first = service.ingest(original)
    duplicate = service.ingest(original)
    conflict = service.ingest(
        candle(
            open_time=original.open_time_utc,
            close_time=original.close_time_utc,
            close="1.1005",
        )
    )

    assert first.status == "accepted"
    assert duplicate.status == "duplicate"
    assert conflict.status == "conflict"
    rows = service.get_candles("EURUSD", "1h")
    assert len(rows) == 1
    assert rows[0]["close"] == "1.1000"
    assert [event["event_type"] for event in service.get_quality_events()] == [
        "duplicate_candle", "duplicate_conflict"
    ]


def test_stale_and_out_of_order_bars_generate_quality_events():
    service = MarketDataService(store, max_staleness_seconds=30)
    now = datetime.now(UTC)
    newer = candle(
        open_time=now - timedelta(minutes=59),
        close_time=now - timedelta(seconds=10),
    )
    older = candle(
        open_time=now - timedelta(hours=3),
        close_time=now - timedelta(hours=2, minutes=1),
    )

    service.ingest(newer)
    result = service.ingest(older)

    assert result.status == "accepted"
    assert set(result.quality_events) == {"stale_candle", "out_of_order_candle"}
    types = {event["event_type"] for event in service.get_quality_events()}
    assert {"stale_candle", "out_of_order_candle"} <= types


def test_closed_bar_and_health_status_are_explicit():
    service = MarketDataService(store)
    assert service.health()["trading_input_eligible"] is False
    result = service.ingest(candle(is_closed=False))
    assert result.status == "accepted"
    assert service.get_candles("EURUSD", "1h")[0]["is_closed"] is False
    assert service.health()["trading_input_eligible"] is False


def test_market_data_api_ingests_lists_and_reports_health():
    payload = candle().model_dump(mode="json")
    accepted = client.post("/api/market-data/candles", json=payload)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    fetched = client.get(
        "/api/market-data/candles", params={"symbol": "EURUSD", "timeframe": "1h"}
    )
    assert fetched.status_code == 200
    assert len(fetched.json()["candles"]) == 1
    assert fetched.json()["candles"][0]["open_time_utc"].endswith("+00:00")

    health = client.get("/api/market-data/health")
    assert health.status_code == 200
    assert health.json()["trading_input_eligible"] is True


def test_market_data_api_rejects_naive_timestamp():
    payload = candle().model_dump(mode="json")
    payload["open_time_utc"] = "2026-01-01T10:00:00"
    response = client.post("/api/market-data/candles", json=payload)
    assert response.status_code == 422


def test_future_dated_candle_is_rejected_and_recorded():
    service = MarketDataService(store)
    now = datetime.now(UTC)
    candidate = candle(
        open_time=now - timedelta(minutes=59),
        close_time=now + timedelta(minutes=10),
    )

    result = service.ingest(candidate)

    assert result.status == "rejected"
    assert result.quality_events == ["future_timestamp"]
    assert service.get_candles("EURUSD", "1h") == []
    assert service.get_quality_events()[-1]["event_type"] == "future_timestamp"

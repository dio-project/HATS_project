from datetime import UTC, datetime, timedelta

import pytest

from hats_api.market_data import MarketDataService
from hats_api.replay import CSVReplayAdapter, CSVReplayError
from hats_api.storage import ConfigStore

HEADER = (
    "symbol,timeframe,open_time_utc,close_time_utc,open,high,low,close,"
    "is_closed,volume,sequence,source_timestamp,source_timezone\n"
)


@pytest.fixture
def service(tmp_path):
    store = ConfigStore(database_url=f"sqlite:///{tmp_path / 'replay.db'}")
    store.initialize()
    return MarketDataService(store)


def row(open_time: datetime, close_time: datetime, close: str = "1.1000") -> str:
    return (
        f"EURUSD,1h,{open_time.isoformat()},{close_time.isoformat()},"
        f"1.0990,1.1010,1.0980,{close},true,100,7,"
        "2026-10-25T12:00:00,Europe/London\n"
    )


def write_csv(tmp_path, content: str):
    path = tmp_path / "candles.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_replay_ingests_canonical_candles_and_is_idempotent(tmp_path, service):
    now = datetime.now(UTC)
    path = write_csv(
        tmp_path,
        HEADER + row(now - timedelta(hours=1), now - timedelta(seconds=5)),
    )
    adapter = CSVReplayAdapter()

    first = adapter.replay(path, service)
    second = adapter.replay(path, service)

    assert first.records_read == 1
    assert first.accepted == 1
    assert first.duplicates == 0
    assert second.duplicates == 1
    assert service.get_candles("EURUSD", "1h")[0]["source"] == "csv-replay"


def test_replay_preserves_file_order_for_quality_detection(tmp_path, service):
    now = datetime.now(UTC)
    newer = row(now - timedelta(hours=1), now - timedelta(minutes=1))
    older = row(
        now - timedelta(hours=3),
        now - timedelta(hours=2, minutes=1),
        close="1.0995",
    )
    path = write_csv(tmp_path, HEADER + newer + older)

    report = CSVReplayAdapter().replay(path, service)

    assert report.accepted == 2
    assert report.quality_event_count == 2
    event_types = {event["event_type"] for event in service.get_quality_events()}
    assert "out_of_order_candle" in event_types
    assert "stale_candle" in event_types


def test_replay_rejects_naive_timestamps_with_line_number(tmp_path):
    path = write_csv(
        tmp_path,
        HEADER
        + "EURUSD,1h,2026-10-25T12:00:00,2026-10-25T13:00:00,"
        "1.0990,1.1010,1.0980,1.1000,true,100,1,,\n",
    )

    with pytest.raises(CSVReplayError, match="CSV line 2"):
        list(CSVReplayAdapter().iter_candles(path))


def test_replay_rejects_unknown_columns_and_malformed_boolean(tmp_path):
    unknown = write_csv(tmp_path, HEADER.rstrip() + ",provider_magic\n")
    with pytest.raises(CSVReplayError, match="unknown columns"):
        list(CSVReplayAdapter().iter_candles(unknown))

    now = datetime.now(UTC)
    malformed = write_csv(
        tmp_path,
        HEADER
        + row(now - timedelta(hours=1), now - timedelta(seconds=5)).replace(
            ",true,", ",sometimes,"
        ),
    )
    with pytest.raises(CSVReplayError, match="is_closed"):
        list(CSVReplayAdapter().iter_candles(malformed))


def test_replay_rejects_duplicate_headers_and_extra_row_fields(tmp_path):
    duplicate_header = write_csv(
        tmp_path, HEADER.replace("symbol,timeframe", "symbol,symbol")
    )
    with pytest.raises(CSVReplayError, match="duplicate column"):
        list(CSVReplayAdapter().iter_candles(duplicate_header))

    now = datetime.now(UTC)
    extra_field = write_csv(
        tmp_path,
        HEADER + row(now - timedelta(hours=1), now - timedelta(seconds=5)).rstrip()
        + ",unexpected\n",
    )
    with pytest.raises(CSVReplayError, match="extra fields"):
        list(CSVReplayAdapter().iter_candles(extra_field))


def test_empty_file_and_invalid_source_are_rejected(tmp_path):
    path = write_csv(tmp_path, "")
    with pytest.raises(CSVReplayError, match="empty"):
        list(CSVReplayAdapter().iter_candles(path))
    with pytest.raises(ValueError, match="must not be empty"):
        CSVReplayAdapter("  ")

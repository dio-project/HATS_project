# Market-data foundation

## Scope

This milestone establishes a canonical candle contract, a provider adapter protocol,
durable storage, quality-event recording, and API visibility. It does **not** connect
to a real OHLCV vendor and does not enable trading. Provider SDKs and credentials are
intentionally absent until a provider is selected.

## Canonical candle contract

```json
{
  "schema_version": 1,
  "symbol": "EURUSD",
  "timeframe": "1h",
  "open_time_utc": "2026-10-25T10:00:00+00:00",
  "close_time_utc": "2026-10-25T11:00:00+00:00",
  "open": "1.16000",
  "high": "1.16100",
  "low": "1.15900",
  "close": "1.16050",
  "volume": null,
  "is_closed": true,
  "source": "provider-id",
  "sequence": 12345,
  "source_timestamp": "raw timestamp as provided by the source",
  "source_timezone": "Europe/London"
}
```

- Timestamp values must include an offset and are normalized to UTC on validation.
- Preserve the raw source timestamp and source IANA zone when the provider supplies them.
  The adapter must document whether its timestamps represent candle open or candle close.
- OHLC values use decimal representations. The API rejects invalid ranges and does not
  synthesize or interpolate missing prices.
- Supported timeframe identifiers currently include 5m, 15m, 30m, 1h, 5h, 12h and 1d.
  Higher-timeframe aggregation and session anchoring are not implemented in this milestone.
- A forming candle is stored with `is_closed: false`; downstream closed-bar models
  must not consume it.

## Provider adapter boundary

`apps/api/hats_api/market_providers.py` defines the `MarketDataProvider` protocol.
An adapter is responsible for symbol mapping, provider-specific timestamp interpretation,
DST/session semantics, sequence/revision behavior, and provider health. It must return
canonical `CandleEvent` objects; it must not silently guess an ambiguous local time.

No provider adapter is currently implemented. `source` identifies the adapter/source
that produced a candle, not a broker account.

## Quality and duplicate behavior

- Identical repeats are idempotent and create a `duplicate_candle` quality event.
- A conflicting repeat for the same source, symbol, timeframe and open time is not
  allowed to overwrite the stored candle; it returns HTTP 409 and records
  `duplicate_conflict`.
- Stale and out-of-order candles are stored for inspection/backfill but create explicit
  quality events. Their presence must not be interpreted as permission to use them for
  trading decisions. The freshness threshold is currently a service default, not a
  per-provider calibrated policy.
- Malformed OHLC, naive timestamps, unsupported timeframes and unknown IANA zones are
  rejected by request validation (HTTP 422). Candle close times more than 60 seconds
  ahead of the API clock are rejected and recorded as a `future_timestamp` error.
  That tolerance is a bootstrap default and must become provider-configurable after
  clock synchronization and provider latency are measured.
- Missing intervals are not fabricated. Detection of expected session gaps, exchange/FX
  holidays, feed clock skew and provider-specific revision policy remains future work.
- `/api/market-data/health` is a preliminary health view, not yet a full per-symbol
  eligibility gate for the strategy pipeline. Layer 1–3 inference is not wired to it.

## API endpoints

- `POST /api/market-data/candles` — ingest a canonical candle.
- `GET /api/market-data/candles?symbol=EURUSD&timeframe=1h&limit=500` — retrieve bars
  in ascending open-time order (up to 5,000).
- `GET /api/market-data/quality?limit=100` — inspect recorded quality events.
- `GET /api/market-data/health` — inspect the latest ingested candle and preliminary
  freshness eligibility.

These endpoints are development scaffolding and do not yet include authentication or
authorization. Do not expose them publicly or connect them to live execution.

## Next work

1. Implement one selected provider adapter with documented source-time semantics.
2. Add per-symbol/timeframe freshness and clock-skew monitoring.
3. Specify missing-bar/session calendars and candle correction/revision rules.
4. Add provider contract tests, historical backfill, and higher-timeframe aggregation.
5. Gate Layer 1 inputs on a durable, per-symbol market-data eligibility decision.

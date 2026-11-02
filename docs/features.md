# Deterministic feature pipeline

## Design

HATS computes one shared, deterministic feature snapshot from closed canonical
candles, then exposes three explicit projections:

- **Layer 1 — environment:** multi-bar returns, realized volatility, normalized
  ATR, normalized EMA spread, and rolling range position.
- **Layer 2 — phase:** EMA levels, RSI, range position, candle body/wick
  structure, close location, short return, and normalized ATR.
- **Layer 3 — entry:** short returns, ATR, RSI, normalized EMA spread, candle
  structure, close location, and range position.

The projections are views over the same versioned calculations. They are not
three independently maintained indicator implementations. Each model adapter
may later define a stricter, separately versioned input contract and select
only approved fields. No feature is automatically considered predictive or
suitable for a model simply because it is available.

## Core feature definitions

All values are computed using Decimal arithmetic from source-specific, closed
OHLC candles in ascending UTC order:

- `return_1`, `return_5`: close-to-close simple returns over 1 and 5 bars.
- `ema_20`, `ema_50`: exponential moving averages seeded with a simple
  moving average over the first full period.
- `atr_14`: Wilder-smoothed average true range.
- `atr_pct`: ATR divided by the latest close.
- `rsi_14`: Wilder RSI; a flat sequence returns 50 and a zero-loss rising
  sequence returns 100.
- `realized_volatility_20`: population standard deviation of the last 20
  natural-log close returns.
- `ema_spread_atr`: EMA(20) minus EMA(50), divided by ATR(14); null when
  either EMA is unavailable or ATR is zero.
- `range_position_20`: latest close's position within the highest high and
  lowest low of the latest 20 bars.
- `candle_body_ratio`, `upper_wick_ratio`, `lower_wick_ratio`,
  `close_location`: current candle geometry normalized by its high-low
  range; all are zero for a zero-range candle.

No tick volume, inferred bars, interpolation, future data, or forming candle
is used. Rolling windows are bar-count based. Session-gap interpretation is
not guessed; provider-specific FX calendar semantics remain a separate task.

## Warm-up and eligibility

The calculation uses a fixed maximum lookback of 500 closed bars and a shared warm-up threshold of 50 closed bars. The lookback is fixed rather than caller-selectable so the same immutable input key cannot silently produce different feature values because a request used a different history length. Before that threshold, available short-window features may be returned, but
the snapshot is marked `insufficient_warmup` and is not eligible as a feature
input. Freshness uses provisional timeframe-specific limits: 15m for 5m bars,
45m for 15m, 90m for 30m, 3h for 1h, 15h for 5h, 36h for 12h, and 72h for 1d.
A stale latest closed candle is marked `stale_input`; a candle whose close
timestamp is still in the future is marked `future_input`. These wall-clock
limits are bootstrap values, not a session calendar. Provider-specific trading
sessions, holidays, weekend reopen, and feed outages must be distinguished
before live eligibility is enabled. Historical snapshots can still be
generated for offline research, but these flags must be respected by any
downstream live pipeline.

This is a preliminary feature-input eligibility check, not a complete
market-data gate or Layer 4 risk authorization. It does not authorize orders.

## Versioning and persistence

- Feature set version: `core-v1`.
- Feature schema version: `1`.
- Snapshot identity: symbol + timeframe + source + candle close timestamp +
  feature-set version.
- Recomputing an identical input is idempotent. If the same immutable key
  produces different values, the pipeline raises a conflict rather than
  overwriting the stored snapshot.
- A changed feature definition requires a new feature-set version. Do not
  reinterpret historical snapshots in place.
- Snapshots are persisted separately from raw candles and include the input
  window start, input count, SHA-256 digest of ordered source-candle payloads,
  separate feature-output digest, and computation timestamp. A changed source
  history under the same snapshot identity is a conflict, not an overwrite.

## API

- `POST /api/features/compute?symbol=EURUSD&timeframe=1h&source=<source>`
  computes and persists the latest snapshot from closed candles for exactly
  that source.
- `GET /api/features/latest?symbol=EURUSD&timeframe=1h&source=<source>`
  retrieves the latest persisted snapshot.

These are development endpoints without authentication or authorization.
They are not connected to Layers 1–4 or live execution.

## Failure semantics and remaining work

No closed candles returns a typed error. Missing sources do not fall back to a
different provider. Forming candles are excluded. Non-finite arithmetic is
rejected. Persistence is protected by a unique input key and digest check;
concurrent duplicate computations resolve to the existing identical snapshot.

Before production use, add provider-specific gap/session calendars, revision
and correction handling, full data-lineage references, feature backfill
orchestration, resource/time limits, metrics and alerting, PostgreSQL
concurrency/integration tests, property-based tests, and a model-specific
feature compatibility registry. Model inference must independently reject
wrong schema versions, stale snapshots, unexpected nulls, and mismatched
training/serving feature definitions.

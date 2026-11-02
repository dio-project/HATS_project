# Deterministic CSV market-data replay

The CSV replay adapter provides a deterministic, offline source for exercising
the canonical candle contract and persistence pipeline while the live provider
and broker decisions remain open. It is not a market-data vendor integration
and must not be treated as a live feed.

## Input schema

Required columns:

- `symbol`
- `timeframe` (one of `5m`, `15m`, `30m`, `1h`, `5h`, `12h`, `1d`)
- `open_time_utc`, `close_time_utc`
- `open`, `high`, `low`, `close`
- `is_closed` (`true`/`false` or `1`/`0`)

Optional columns:

- `volume`
- `sequence`
- `source_timestamp` (original provider timestamp for traceability)
- `source_timezone` (IANA timezone identifier for traceability)

Timestamps must be ISO-8601 values with an explicit UTC offset, for example
`2026-10-25T01:00:00+00:00`. The adapter does not interpret naive timestamps,
infer a timezone, resolve DST folds, or repair malformed OHLC values. Convert
vendor-specific timestamp conventions in a dedicated provider adapter before
constructing canonical candles.

## Run a replay

From the repository root, after installing the project and applying migrations, generate a recent synthetic sample and replay it:

```bash
python scripts/generate_replay_sample.py
python -m hats_api.replay_cli ./examples/data/eurusd_1h.csv --source synthetic-sample
```

The generator creates closed hourly bars ending at the most recently completed UTC hour, so the sample remains within the default freshness window. Its prices are deterministic synthetic values for UI and pipeline testing only; they are not historical or live EURUSD prices. You can change the output path and bar count, for example:

```bash
python scripts/generate_replay_sample.py ./data/eurusd.csv --bars 48
python -m hats_api.replay_cli ./data/eurusd.csv --source synthetic-sample
```

The CLI uses `HATS_DATABASE_URL` or `DATABASE_URL` when configured; otherwise
it uses the local SQLite database. An explicit SQLAlchemy URL can be passed with
`--database-url`. Keep credentials out of command history and source control.

The command prints a JSON report with records read, accepted bars, duplicates,
conflicts, rejected bars, and quality-event count. The same source + symbol +
timeframe + open-time key is idempotent. Conflicting duplicates are not
overwritten. Existing market-data quality rules record stale and out-of-order
bars; future-dated bars are rejected.

## Failure and operational semantics

Replay is sequential and fail-fast. If a malformed row is encountered, the
command exits with an error and reports its CSV line number. Earlier rows in
that file may already have been committed; replay is not one all-or-nothing
database transaction. For a controlled historical backfill, validate the
complete file before running it against a durable shared database, and take a
database backup first.

CSV order is preserved intentionally so out-of-order observations remain
visible to the quality monitor. The adapter does not silently sort, deduplicate,
aggregate timeframes, fill gaps, or synthesize candles. Use disposable test
databases for experiments.

This adapter is a development and validation tool. It does not start a worker,
schedule recurring imports, expose a file-upload endpoint, connect a provider,
enable trading, or bypass Layer 4. Live-provider adapters must separately define
authentication, rate limits, pagination/backfill, retry policy, source clock
semantics, session calendars, and freshness behavior.

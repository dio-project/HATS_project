# HATS — Hierarchical Automated Trading System

HATS is a modular, paper-first intraday FX system under development. The foundation includes a React control plane, a validated configuration API, explicit confirmation before activation, UTC/time-zone utilities, canonical market-data contracts and persistence, and automated tests. It is NOT ready for live trading.

## Current decisions

- Predictive Layer 1 (environment), Layer 2 (phase), Layer 3 (entry proposal).
- Layer 4 is deterministic risk authorization with absolute veto authority.
- Layer 3B/Sentinel is removed from the current pipeline.
- Paper mode by default. Canonical candle ingestion and persistence are implemented, but no live OHLCV provider or broker adapter is active.
- Entry orders are limit-only; an unfilled entry expires. No market-order fallback. Protective stop/exit mechanisms are distinct from entry type.
- Layer settings are editable in the frontend, validated by the backend, and activated only after review and explicit confirmation.
- Active configuration, version snapshots, pending drafts, audit events, market candles and market-data quality events are stored in a database. SQLite is the local default; PostgreSQL is supported.

## Run in Codespaces or locally

Python 3.12+, Node 20+.

    python -m pip install -e ".[dev]"
    alembic upgrade head
    uvicorn hats_api.main:app --reload --app-dir apps/api

In another terminal:

    cd apps/web
    npm install
    npm run dev

Open forwarded port 5173. The API runs on port 8000; Vite proxies API requests to it by default, which is compatible with Codespaces. Set VITE_API_BASE_URL only when the API is hosted at a separate base URL. Run backend tests with python -m pytest; run lint with python -m ruff check apps/api tests; build the frontend with cd apps/web && npm run build.

By default, local development uses .hats/hats.db. Set HATS_DATABASE_URL to override the database URL. For PostgreSQL, install the project dependencies and set a URL such as postgresql+psycopg://user:password@host:5432/hats. Do not commit credentials or database files.

The initial risk values (1% default trade risk, 0.5% drawdown throttle, 2% daily equity loss lockout, 5% rolling drawdown trigger) are provisional defaults, not validated trading recommendations. Codespaces is a development environment, not a live execution host.

Market-data contracts and quality semantics are documented in docs/market-data.md. The Broker & Data UI reads candle, health, and quality endpoints; Overview reads system status and backend time; configuration and audit views use their respective APIs. The endpoint-to-screen mapping is documented in docs/frontend-api.md. Market data is not yet wired to Layers 1–4. Do not expose development endpoints publicly.

See docs/architecture.md, docs/time-semantics.md, docs/market-data.md, docs/frontend-api.md, and docs/operations.md.

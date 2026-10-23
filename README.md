# HATS — Hierarchical Automated Trading System

HATS is a modular, paper-first intraday FX system under development. This initial foundation includes a React control plane, a validated configuration API, explicit confirmation before backend activation, UTC/time-zone utilities, and tests. It is NOT ready for live trading.

## Current decisions
- Predictive Layer 1 (environment), Layer 2 (phase), Layer 3 (entry proposal).
- Layer 4 is deterministic risk authorization with absolute veto authority.
- Layer 3B/Sentinel is removed from the current pipeline.
- Paper mode by default. No broker or OHLCV adapter is active.
- Entry orders are limit-only; an unfilled entry expires. No market-order fallback. Protective stop/exit mechanisms are distinct from entry type.
- Layer settings are editable in the frontend, validated by the backend, and activated only after review and explicit confirmation.

## Run in Codespaces or locally
Python 3.12+, Node 20+.

    pip install -e ".[dev]"
    uvicorn hats_api.main:app --reload --app-dir apps/api

In another terminal:

    cd apps/web
    npm install
    npm run dev

Open port 5173. API runs on port 8000. Run backend tests with pytest; build frontend with npm run build from apps/web.

Initial risk values (1% default trade risk, 0.5% drawdown throttle, 2% daily equity loss lockout, 5% rolling drawdown trigger) are provisional defaults, not validated trading recommendations. The API configuration and audit state are in-memory and must be replaced with transactional durable storage before multi-user or production use. Codespaces is a development environment, not a live execution host.

See docs/architecture.md, docs/time-semantics.md and docs/operations.md.

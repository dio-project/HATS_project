# Development and operations

## Start in Codespaces or locally

Python 3.12+ and Node 20+ are required.

1. Install the project and development dependencies: `python -m pip install -e ".[dev]"`.
2. Apply database migrations: `alembic upgrade head`.
3. Start the API from the repository root: `uvicorn hats_api.main:app --reload --app-dir apps/api`.
4. In a second terminal, run `cd apps/web && npm install && npm run dev`.
5. Open forwarded port 5173 for the frontend; the API listens on port 8000. Vite proxies `/api/*` and `/health` to the API, so browser requests work through the forwarded frontend port. For a separately hosted API, configure `VITE_API_BASE_URL` before building the frontend.

By default, local development uses a durable SQLite database at `.hats/hats.db`. Set `HATS_DATABASE_URL` to override it. PostgreSQL is supported with a SQLAlchemy URL such as `postgresql+psycopg://user:password@host:5432/hats`. Keep credentials in environment secrets, never in source control.

The API bootstraps missing tables for a new development database. Schema changes to an existing database must be applied with Alembic; do not rely on `create_all` to alter existing tables. Before deploying against a persistent database, take a backup and run `alembic upgrade head` as a controlled deployment step.

## Apply a settings change

Edit a setting, select Review & confirm, inspect the version/digest, and type APPLY CONFIG. The backend validates the draft against the expected active version, rechecks the version inside a database transaction, activates the new version, and writes an audit event in the same transaction. Stale drafts return a conflict and must be reviewed again.

## Configuration history and audit

The Configurations section lists durable versioned snapshots and lets a user load a snapshot into the editor. Loading a snapshot does not activate it; the normal review/confirmation workflow is still required. Clearing configuration history requires typing CLEAR HISTORY and retains the active snapshot. Audit events are stored separately and are not deleted when configuration history is cleared.

The database persists active configuration, configuration snapshots, pending drafts, and audit events across API restarts. The current audit API returns the most recent 100 events. SQLite is intended for single-instance development; use PostgreSQL for a shared or production database. Production still requires authentication, authorization, backup/restore procedures, access controls, and monitored database availability.

## Before live trading

This repository is not live-trading capable. Required gates include authentication/authorization; secure credentials; broker capability discovery; market-data normalization and quality checks; deterministic Layer 4 risk engine integration; idempotent order submission and reconciliation; operational pause/kill controls; alerts/metrics; recovery procedures; and independently reviewed tests.

Test duplicate submissions, partial fills, unknown order status after timeout, reconnect and restart, stale/out-of-order bars, DST transitions, weekends/session boundaries, spread widening, price gaps, daily-loss and drawdown breaches, and rejected protective orders. Never commit secrets or production environment files.


## Frontend API integration

The Overview displays backend-reported system status and clock values. Broker & Data displays persisted candles, global market-data health, and quality events from the backend API. Configuration and audit screens use the configuration/history/audit endpoints. See `docs/frontend-api.md` for the route-to-screen map and the limitations of the preliminary market-data health flag.

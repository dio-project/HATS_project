# Development and operations

## Start
Install Python 3.12+ and Node 20+. Run pip install -e ".[dev]", then uvicorn hats_api.main:app --reload --app-dir apps/api. In another terminal run npm install and npm run dev from apps/web. Open port 5173; API is port 8000.

## Apply a settings change
Edit a setting, select Review & confirm, inspect the version/digest, and type APPLY CONFIG. The API activates the new version or returns a validation/conflict error. Edits made while the API is offline are local only and are not active backend settings.

## Before live trading
This repository is not live-trading capable. Required gates include durable config and risk state; authentication/authorization; secure credentials; broker capability discovery; market-data normalization and quality checks; deterministic risk engine integration; idempotent order submission and reconciliation; operational pause/kill controls; alerts/metrics; recovery procedures; and independently reviewed tests.

Test duplicate submissions, partial fills, unknown order status after timeout, reconnect and restart, stale/out-of-order bars, DST transitions, weekends/session boundaries, spread widening, price gaps, daily-loss and drawdown breaches, and rejected protective orders. Never commit secrets or production environment files.

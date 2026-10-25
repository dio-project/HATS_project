# Frontend-to-backend API map

The frontend control plane calls the backend through the Vite development proxy by default. Set `VITE_API_BASE_URL` only when the frontend must call an API hosted at a different base URL. Never put provider credentials or other secrets in frontend environment variables.

## Overview

| Backend endpoint | Frontend use | Notes |
|---|---|---|
| `GET /api/config` | Initial configuration load and API connectivity indicator | Connectivity means the configuration API responded; it does not imply broker connectivity. |
| `GET /api/system/status` | Overview → System status & time | Shows backend-reported execution mode, pipeline stages, broker flag, trading flag, and Layer 3B state. |
| `GET /api/time/now?timezone_name=UTC` | Overview → Backend clock | Displays UTC and a selectable IANA time zone. Backend timestamps remain authoritative. |

## Configuration control

| Backend endpoint | Frontend use |
|---|---|
| `POST /api/config/drafts` | Layer Rules and Risk & Guardrails → Review & confirm |
| `POST /api/config/confirm` | Explicit `APPLY CONFIG` confirmation |
| `GET /api/config/history` | Configurations tab |
| `GET /api/config/history/{version}` | Load a saved version into the editor |
| `POST /api/config/history/clear` | Clear history after typing `CLEAR HISTORY` |
| `GET /api/audit` | System Logs tab |

Restoring a configuration never activates it automatically. The backend remains responsible for validation, optimistic-version checks, explicit confirmation, atomic activation, and audit records.

## Market data

The Broker & Data tab contains a market-data observability view. It fetches these endpoints concurrently and refreshes every 30 seconds while open:

| Backend endpoint | UI behavior |
|---|---|
| `GET /api/market-data/health` | Ingestion status, global latest stored candle time, age, and preliminary eligibility flag |
| `GET /api/market-data/candles?symbol=...&timeframe=...&limit=...` | Filterable table of stored OHLCV bars |
| `GET /api/market-data/quality?limit=100` | Newest-first quality events and expandable event details |
| `POST /api/market-data/candles` | Ingestion contract for an internal adapter or test client; intentionally not exposed as a manual operator action |

The health response is currently global, not per symbol/timeframe. The UI labels this limitation and explicitly warns that the preliminary eligibility flag is not a Layer 4 authorization decision. A fresh test candle does not mean a live provider is connected. The UI must continue to report provider integration as pending until a real adapter is configured and verified.

## Development proxy and deployment

During local development and in Codespaces, Vite proxies `/api/*` and `/health` to `http://127.0.0.1:8000`. This avoids hard-coding `localhost:8000` into browser requests, which can point at the user's own machine instead of the Codespaces container. For a separately hosted frontend, configure `VITE_API_BASE_URL` at build time to the API base URL and configure backend CORS/authentication for that deployment.

These APIs are currently development-only and do not implement user authentication or authorization. Do not expose the control plane publicly or connect it to live execution.

"""HATS configuration, health, and market-data API."""
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from hats_api.config import ConfirmRequest, DraftRequest
from hats_api.market_data import CandleEvent, MarketDataService
from hats_api.storage import (
    ConfigStore,
    DraftNotFound,
    InvalidConfirmation,
    VersionConflict,
)

app = FastAPI(title="HATS API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

store = ConfigStore()
store.initialize()
market_data = MarketDataService(store)


def utc_now():
    return datetime.now(UTC)


def validate_timezone(name: str):
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown IANA time zone: {name}"
        ) from exc


@app.get("/health")
def health():
    active = store.get_active()
    return {"status": "ok", "execution_mode": active.layer4.execution_mode, "utc": utc_now()}


@app.get("/api/config")
def get_config():
    return {"active": store.get_active().model_dump(mode="json"), "drafts_require_confirmation": True}


@app.get("/api/audit")
def get_audit():
    return {"events": store.get_audit(limit=100)}


@app.get("/api/config/history")
def get_config_history():
    return store.get_history()


@app.get("/api/config/history/{version}")
def get_config_version(version: int):
    item = store.get_version(version)
    if item is None:
        raise HTTPException(status_code=404, detail="Configuration version not found")
    return item


@app.post("/api/config/history/clear")
def clear_config_history(payload: dict):
    if payload.get("confirmation_phrase") != "CLEAR HISTORY":
        raise HTTPException(status_code=400, detail="Confirmation phrase does not match")
    retained_version = store.clear_history()
    return {"status": "cleared", "active_version_retained": retained_version}


@app.post("/api/config/drafts")
def create_draft(request: DraftRequest):
    candidate = request.proposed_config
    validate_timezone(candidate.layer4.daily_reset_timezone)
    if candidate.layer3.rules.get("entry_order_type", "limit") != "limit":
        raise HTTPException(status_code=422, detail="Entry order type must remain limit")
    if candidate.layer3.rules.get("market_order_fallback", False) is not False:
        raise HTTPException(status_code=422, detail="Market-order fallback is prohibited")
    try:
        return store.create_draft(
            expected_version=request.expected_version,
            candidate=candidate,
            draft_id=str(uuid4()),
        )
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Active configuration changed; reload before editing.",
                "active_version": exc.active_version,
            },
        ) from exc


@app.post("/api/config/confirm")
def confirm_draft(request: ConfirmRequest):
    try:
        return store.confirm_draft(request.draft_id, request.confirmation_phrase)
    except InvalidConfirmation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Active config changed to version {exc.active_version}; create a new draft",
        ) from exc


@app.get("/api/time/now")
def time_now(timezone_name: str = "UTC"):
    validate_timezone(timezone_name)
    instant = utc_now()
    return {
        "utc": instant.isoformat(),
        "timezone": timezone_name,
        "local": instant.astimezone(ZoneInfo(timezone_name)).isoformat(),
        "unix_ms": int(instant.timestamp() * 1000),
    }


@app.post("/api/market-data/candles")
def ingest_market_candle(candle: CandleEvent):
    result = market_data.ingest(candle)
    if result.status == "conflict":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A different candle already exists for this source and interval.",
                **result.model_dump(),
            },
        )
    return result.model_dump()


@app.get("/api/market-data/candles")
def get_market_candles(
    symbol: str = Query(min_length=3, max_length=20),
    timeframe: str = Query(pattern="^(5m|15m|30m|1h|5h|12h|1d)$"),
    limit: int = Query(default=500, ge=1, le=5000),
):
    return {"candles": market_data.get_candles(symbol, timeframe, limit)}


@app.get("/api/market-data/quality")
def get_market_data_quality(limit: int = Query(default=100, ge=1, le=1000)):
    return {"events": market_data.get_quality_events(limit)}


@app.get("/api/market-data/health")
def get_market_data_health():
    return market_data.health()


@app.get("/api/system/status")
def system_status():
    active = store.get_active()
    return {
        "execution_mode": active.layer4.execution_mode,
        "pipeline": ["market_data", "layer1", "layer2", "layer3", "layer4_risk"],
        "layer3b_enabled": False,
        "broker_connected": False,
        "trading_enabled": False,
        "note": "Market-data contracts and persistence are available; no provider or broker execution is active.",
    }

"""HATS configuration and health API. State is in-memory for local development only."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from hats_api.config import ConfirmRequest, DraftRequest, SystemConfig

app = FastAPI(title="HATS API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
_active = SystemConfig()
_drafts: dict[str, dict] = {}
_audit: list[dict] = []
_history: list[dict] = [{"version": _active.version, "updated_at": _active.updated_at.isoformat(), "config": _active.model_dump(mode="json"), "label": "Initial defaults"}]

def utc_now():
    return datetime.now(timezone.utc)

def validate_timezone(name: str):
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Unknown IANA time zone: {name}") from exc

@app.get("/health")
def health():
    return {"status": "ok", "execution_mode": _active.layer4.execution_mode, "utc": utc_now()}

@app.get("/api/config")
def get_config():
    return {"active": _active.model_dump(mode="json"), "drafts_require_confirmation": True}

@app.get("/api/audit")
def get_audit():
    return {"events": deepcopy(_audit[-100:])}

@app.get("/api/config/history")
def get_config_history():
    return {"configurations": [{"version": item["version"], "updated_at": item["updated_at"], "label": item["label"]} for item in reversed(_history)], "active_version": _active.version}

@app.get("/api/config/history/{version}")
def get_config_version(version: int):
    item = next((entry for entry in _history if entry["version"] == version), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Configuration version not found")
    return {"configuration": deepcopy(item["config"]), "label": item["label"]}

@app.post("/api/config/history/clear")
def clear_config_history(payload: dict):
    global _history
    if payload.get("confirmation_phrase") != "CLEAR HISTORY":
        raise HTTPException(status_code=400, detail="Confirmation phrase does not match")
    _history = [{"version": _active.version, "updated_at": _active.updated_at.isoformat(), "config": _active.model_dump(mode="json"), "label": "Active configuration (retained)"}]
    _audit.append({"at": utc_now().isoformat(), "event": "config_history_cleared", "active_version_retained": _active.version})
    return {"status": "cleared", "active_version_retained": _active.version}

@app.post("/api/config/drafts")
def create_draft(request: DraftRequest):
    if request.expected_version != _active.version:
        raise HTTPException(status_code=409, detail={"message": "Active configuration changed; reload before editing.", "active_version": _active.version})
    candidate = request.proposed_config
    validate_timezone(candidate.layer4.daily_reset_timezone)
    if candidate.layer3.rules.get("entry_order_type", "limit") != "limit":
        raise HTTPException(status_code=422, detail="Entry order type must remain limit")
    if candidate.layer3.rules.get("market_order_fallback", False) is not False:
        raise HTTPException(status_code=422, detail="Market-order fallback is prohibited")
    candidate.version = _active.version + 1
    candidate.updated_at = utc_now()
    draft_id = str(uuid4())
    snapshot = candidate.model_dump(mode="json")
    digest = sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    _drafts[draft_id] = {"config": snapshot, "digest": digest, "base_version": _active.version}
    _audit.append({"at": utc_now().isoformat(), "event": "config_draft_created", "draft_id": draft_id, "base_version": _active.version, "digest": digest})
    return {"draft_id": draft_id, "digest": digest, "requires_confirmation_phrase": "APPLY CONFIG", "proposed_config": snapshot}

@app.post("/api/config/confirm")
def confirm_draft(request: ConfirmRequest):
    global _active
    draft = _drafts.get(request.draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found or already consumed")
    if request.confirmation_phrase != "APPLY CONFIG":
        raise HTTPException(status_code=400, detail="Confirmation phrase does not match")
    if draft["base_version"] != _active.version:
        del _drafts[request.draft_id]
        raise HTTPException(status_code=409, detail="Active config changed; create a new draft")
    candidate = SystemConfig.model_validate(draft["config"])
    previous_version = _active.version
    _active = candidate
    _history.append({"version": _active.version, "updated_at": _active.updated_at.isoformat(), "config": _active.model_dump(mode="json"), "label": f"Configuration v{_active.version}"})
    del _drafts[request.draft_id]
    _audit.append({"at": utc_now().isoformat(), "event": "config_activated", "previous_version": previous_version, "active_version": _active.version, "digest": draft["digest"]})
    return {"status": "activated", "active": _active.model_dump(mode="json"), "audit_event_recorded": True}

@app.get("/api/time/now")
def time_now(timezone_name: str = "UTC"):
    validate_timezone(timezone_name)
    instant = utc_now()
    return {"utc": instant.isoformat(), "timezone": timezone_name, "local": instant.astimezone(ZoneInfo(timezone_name)).isoformat(), "unix_ms": int(instant.timestamp() * 1000)}

@app.get("/api/system/status")
def system_status():
    return {"execution_mode": _active.layer4.execution_mode, "pipeline": ["market_data", "layer1", "layer2", "layer3", "layer4_risk"], "layer3b_enabled": False, "broker_connected": False, "trading_enabled": False, "note": "Scaffold only; broker execution is not implemented."}

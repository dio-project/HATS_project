from fastapi.testclient import TestClient
from hats_api.main import app

client = TestClient(app)

def test_health_and_pipeline_excludes_layer3b():
    assert client.get("/health").status_code == 200
    status = client.get("/api/system/status").json()
    assert status["layer3b_enabled"] is False
    assert "layer3b" not in status["pipeline"]

def test_config_requires_confirmation_and_versions():
    active = client.get("/api/config").json()["active"]
    active["layer4"]["default_risk_pct"] = 0.8
    draft = client.post("/api/config/drafts", json={"expected_version": active["version"], "proposed_config": active})
    assert draft.status_code == 200
    draft_id = draft.json()["draft_id"]
    wrong = client.post("/api/config/confirm", json={"draft_id": draft_id, "confirmation_phrase": "yes"})
    assert wrong.status_code == 400
    assert client.get("/api/config").json()["active"]["version"] == 1
    applied = client.post("/api/config/confirm", json={"draft_id": draft_id, "confirmation_phrase": "APPLY CONFIG"})
    assert applied.status_code == 200
    assert applied.json()["active"]["version"] == 2
    assert applied.json()["active"]["layer4"]["default_risk_pct"] == 0.8

def test_invalid_timezone_rejected():
    active = client.get("/api/config").json()["active"]
    active["layer4"]["daily_reset_timezone"] = "Mars/Olympus"
    response = client.post("/api/config/drafts", json={"expected_version": active["version"], "proposed_config": active})
    assert response.status_code == 422

def test_market_fallback_rejected():
    active = client.get("/api/config").json()["active"]
    active["layer3"]["rules"]["market_order_fallback"] = True
    response = client.post("/api/config/drafts", json={"expected_version": active["version"], "proposed_config": active})
    assert response.status_code == 422

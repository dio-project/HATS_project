import os
from pathlib import Path

os.environ["HATS_DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from hats_api.main import app, store
from hats_api.storage import ConfigStore, VersionConflict

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    store.reset_for_tests()


def test_health_and_pipeline_excludes_layer3b():
    assert client.get("/health").status_code == 200
    status = client.get("/api/system/status").json()
    assert status["layer3b_enabled"] is False
    assert "layer3b" not in status["pipeline"]


def test_config_requires_confirmation_and_versions():
    active = client.get("/api/config").json()["active"]
    active["layer4"]["default_risk_pct"] = 0.8
    draft = client.post(
        "/api/config/drafts",
        json={"expected_version": active["version"], "proposed_config": active},
    )
    assert draft.status_code == 200
    draft_id = draft.json()["draft_id"]
    wrong = client.post(
        "/api/config/confirm",
        json={"draft_id": draft_id, "confirmation_phrase": "yes"},
    )
    assert wrong.status_code == 400
    assert client.get("/api/config").json()["active"]["version"] == 1
    applied = client.post(
        "/api/config/confirm",
        json={"draft_id": draft_id, "confirmation_phrase": "APPLY CONFIG"},
    )
    assert applied.status_code == 200
    assert applied.json()["active"]["version"] == 2
    assert applied.json()["active"]["layer4"]["default_risk_pct"] == 0.8


def test_invalid_timezone_rejected():
    active = client.get("/api/config").json()["active"]
    active["layer4"]["daily_reset_timezone"] = "Mars/Olympus"
    response = client.post(
        "/api/config/drafts",
        json={"expected_version": active["version"], "proposed_config": active},
    )
    assert response.status_code == 422


def test_market_fallback_rejected():
    active = client.get("/api/config").json()["active"]
    active["layer3"]["rules"]["market_order_fallback"] = True
    response = client.post(
        "/api/config/drafts",
        json={"expected_version": active["version"], "proposed_config": active},
    )
    assert response.status_code == 422


def test_configuration_history_and_confirmed_clear():
    history = client.get("/api/config/history")
    assert history.status_code == 200
    assert history.json()["configurations"]
    active = client.get("/api/config").json()["active"]
    version = active["version"]
    fetched = client.get(f"/api/config/history/{version}")
    assert fetched.status_code == 200
    assert fetched.json()["configuration"]["version"] == version
    rejected = client.post(
        "/api/config/history/clear", json={"confirmation_phrase": "no"}
    )
    assert rejected.status_code == 400
    cleared = client.post(
        "/api/config/history/clear",
        json={"confirmation_phrase": "CLEAR HISTORY"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["active_version_retained"] == version
    after = client.get("/api/config/history").json()["configurations"]
    assert len(after) == 1
    assert after[0]["version"] == version
    assert client.get("/api/audit").json()["events"][-1]["event"] == "config_history_cleared"


def test_stale_draft_cannot_overwrite_newer_active_config():
    active = client.get("/api/config").json()["active"]
    first = client.post(
        "/api/config/drafts",
        json={"expected_version": 1, "proposed_config": active},
    )
    assert first.status_code == 200
    changed = client.get("/api/config").json()["active"]
    changed["layer4"]["default_risk_pct"] = 0.7
    second = client.post(
        "/api/config/drafts",
        json={"expected_version": 1, "proposed_config": changed},
    )
    assert second.status_code == 200
    activated = client.post(
        "/api/config/confirm",
        json={
            "draft_id": second.json()["draft_id"],
            "confirmation_phrase": "APPLY CONFIG",
        },
    )
    assert activated.status_code == 200
    stale = client.post(
        "/api/config/confirm",
        json={
            "draft_id": first.json()["draft_id"],
            "confirmation_phrase": "APPLY CONFIG",
        },
    )
    assert stale.status_code == 409
    assert client.get("/api/config").json()["active"]["version"] == 2


def test_configuration_survives_store_restart(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    first_store = ConfigStore(database_url)
    first_store.initialize()
    active = first_store.get_active()
    active.layer4.default_risk_pct = 0.75
    draft = first_store.create_draft(
        expected_version=1, candidate=active, draft_id="restart-test-draft"
    )
    first_store.confirm_draft(draft["draft_id"], "APPLY CONFIG")
    first_store.engine.dispose()

    restarted_store = ConfigStore(database_url)
    restarted_store.initialize()
    restored = restarted_store.get_active()
    assert restored.version == 2
    assert restored.layer4.default_risk_pct == 0.75
    assert restarted_store.get_history()["active_version"] == 2
    assert any(
        event["event"] == "config_activated"
        for event in restarted_store.get_audit()
    )
    restarted_store.engine.dispose()


def test_durable_audit_is_not_deleted_when_configuration_history_is_cleared():
    active = client.get("/api/config").json()["active"]
    active["layer4"]["default_risk_pct"] = 0.9
    draft = client.post(
        "/api/config/drafts",
        json={"expected_version": 1, "proposed_config": active},
    ).json()
    client.post(
        "/api/config/confirm",
        json={"draft_id": draft["draft_id"], "confirmation_phrase": "APPLY CONFIG"},
    )
    before = len(client.get("/api/audit").json()["events"])
    cleared = client.post(
        "/api/config/history/clear",
        json={"confirmation_phrase": "CLEAR HISTORY"},
    )
    assert cleared.status_code == 200
    after = client.get("/api/audit").json()["events"]
    assert len(after) == before + 1
    assert after[-1]["event"] == "config_history_cleared"
    assert client.get("/api/config").json()["active"]["version"] == 2

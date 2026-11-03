import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from hats_api.features import FeatureSnapshot
from hats_api.inference import (
    ModelInputContract,
    ModelInputValidationError,
    validate_model_input,
)


def make_snapshot(**overrides):
    payload = {
        "schema_version": 1,
        "feature_set_version": "core-v1",
        "symbol": "EURUSD",
        "timeframe": "1h",
        "source": "test-feed",
        "candle_open_time_utc": datetime.now(UTC) - timedelta(hours=1),
        "candle_close_time_utc": datetime.now(UTC) - timedelta(minutes=1),
        "input_window_start_utc": datetime.now(UTC) - timedelta(days=3),
        "input_digest": "a" * 64,
        "feature_digest": "b" * 64,
        "computed_at_utc": datetime.now(UTC),
        "input_count": 100,
        "features": {"return_1": "0.001", "atr_pct": "0.002"},
        "layer_views": {
            "layer1_environment": {"return_1": "0.001", "atr_pct": "0.002"},
            "layer2_phase": {"return_1": "0.001", "rsi_14": "55"},
            "layer3_entry": {"return_1": "0.001", "atr_14": "0.0004"},
        },
    }
    payload.update({key: value for key, value in overrides.items() if key != "schema_version"})
    supplied_digest = payload["feature_digest"] if "feature_digest" in overrides else None
    serialized = json.dumps(
        {"features": payload["features"], "layer_views": payload["layer_views"]},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    payload["feature_digest"] = (
        supplied_digest or hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    )
    snapshot = FeatureSnapshot.model_validate(payload)
    if "schema_version" in overrides:
        snapshot = snapshot.model_copy(update={"schema_version": overrides["schema_version"]})
    return snapshot


def make_contract(**overrides):
    payload = {
        "layer": "layer1_environment",
        "model_id": "environment-classifier",
        "model_version": "1.0.0",
        "feature_set_version": "core-v1",
        "feature_schema_version": 1,
        "required_features": ("return_1", "atr_pct"),
        "minimum_input_count": 50,
        "maximum_snapshot_age_seconds": 3600,
    }
    payload.update(overrides)
    return ModelInputContract.model_validate(payload)


def test_valid_model_input_preserves_model_and_data_provenance():
    snapshot = make_snapshot()
    contract = make_contract()

    result = validate_model_input(snapshot, contract, now=datetime.now(UTC))

    assert result.layer == "layer1_environment"
    assert result.model_id == "environment-classifier"
    assert result.model_version == "1.0.0"
    assert result.features["return_1"].as_tuple().exponent == -3
    assert result.input_digest == "a" * 64
    assert len(result.feature_digest) == 64


@pytest.mark.parametrize(
    ("snapshot_overrides", "message"),
    [
        ({"schema_version": 2}, "schema version"),
        ({"feature_set_version": "core-v2"}, "(?i)feature set version"),
        ({"input_count": 10}, "below model minimum"),
        ({"input_digest": None}, "provenance"),
        ({"feature_digest": "invalid"}, "output digest"),
        (
            {"candle_close_time_utc": datetime.now(UTC) + timedelta(minutes=1)},
            "in the future",
        ),
    ],
)
def test_incompatible_or_untrusted_snapshot_is_rejected(snapshot_overrides, message):
    with pytest.raises(ModelInputValidationError, match=message):
        validate_model_input(
            make_snapshot(**snapshot_overrides),
            make_contract(),
            now=datetime.now(UTC),
        )


def test_stale_snapshot_is_rejected():
    snapshot = make_snapshot(
        candle_close_time_utc=datetime.now(UTC) - timedelta(hours=2)
    )
    with pytest.raises(ModelInputValidationError, match="freshness"):
        validate_model_input(snapshot, make_contract(), now=datetime.now(UTC))


def test_wrong_layer_projection_is_rejected():
    with pytest.raises(ModelInputValidationError, match="does not contain projection"):
        validate_model_input(
            make_snapshot(
                layer_views={
                    "layer1_environment": {"return_1": "0.001", "atr_pct": "0.002"},
                    "layer2_phase": {"return_1": "0.001", "rsi_14": "55"},
                }
            ),
            make_contract(layer="layer3_entry"),
            now=datetime.now(UTC),
        )


def test_missing_and_null_required_features_are_rejected():
    snapshot = make_snapshot(
        layer_views={
            "layer1_environment": {"return_1": "0.001"},
            "layer2_phase": {},
            "layer3_entry": {},
        }
    )
    with pytest.raises(ModelInputValidationError, match="unavailable features"):
        validate_model_input(snapshot, make_contract(), now=datetime.now(UTC))

    snapshot = make_snapshot(
        layer_views={
            "layer1_environment": {"return_1": "0.001", "atr_pct": None},
            "layer2_phase": {},
            "layer3_entry": {},
        }
    )
    with pytest.raises(ModelInputValidationError, match="atr_pct is null"):
        validate_model_input(snapshot, make_contract(), now=datetime.now(UTC))


def test_explicit_nullable_feature_is_omitted_from_model_vector():
    snapshot = make_snapshot(
        layer_views={
            "layer1_environment": {"return_1": "0.001", "atr_pct": None},
            "layer2_phase": {},
            "layer3_entry": {},
        }
    )
    contract = make_contract(nullable_features=("atr_pct",))

    result = validate_model_input(snapshot, contract, now=datetime.now(UTC))

    assert result.features == {"return_1": result.features["return_1"]}
    assert "atr_pct" not in result.features


def test_non_finite_feature_values_are_rejected():
    snapshot = make_snapshot(
        layer_views={
            "layer1_environment": {"return_1": "NaN", "atr_pct": "0.002"},
            "layer2_phase": {},
            "layer3_entry": {},
        }
    )
    with pytest.raises(ModelInputValidationError, match="not finite"):
        validate_model_input(snapshot, make_contract(), now=datetime.now(UTC))


def test_contract_rejects_duplicate_and_invalid_nullable_feature_names():
    with pytest.raises(ValueError, match="unique"):
        make_contract(required_features=("return_1", "return_1"))
    with pytest.raises(ValueError, match="also be required"):
        make_contract(nullable_features=("ema_50",))


def test_feature_digest_must_match_snapshot_payload():
    snapshot = make_snapshot(feature_digest="c" * 64)
    with pytest.raises(ModelInputValidationError, match="does not match payload"):
        validate_model_input(snapshot, make_contract(), now=datetime.now(UTC))

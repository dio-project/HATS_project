"""Model-serving input contracts for the predictive HATS layers.

This module validates feature snapshots at the model boundary. It does not
implement model inference, strategy policy, order construction, or risk checks.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hats_api.features import FeatureSnapshot


PredictiveLayer = Literal[
    "layer1_environment",
    "layer2_phase",
    "layer3_entry",
]

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ModelInputValidationError(ValueError):
    """Raised when a feature snapshot violates a model's serving contract."""


class ModelInputContract(BaseModel):
    """Immutable declaration of the feature schema expected by one model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: PredictiveLayer
    model_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    feature_set_version: str = Field(min_length=1, max_length=40)
    feature_schema_version: int = Field(ge=1)
    required_features: tuple[str, ...] = Field(min_length=1)
    nullable_features: tuple[str, ...] = ()
    minimum_input_count: int = Field(default=50, ge=1)
    maximum_snapshot_age_seconds: int = Field(default=3600, ge=1)

    @field_validator("required_features", "nullable_features")
    @classmethod
    def validate_feature_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not name.strip() for name in values):
            raise ValueError("Feature names must not be empty")
        if len(values) != len(set(values)):
            raise ValueError("Feature names must be unique")
        return values

    @field_validator("nullable_features")
    @classmethod
    def nullable_must_be_required(cls, values: tuple[str, ...], info):
        required = info.data.get("required_features", ())
        if not set(values).issubset(required):
            raise ValueError("Nullable features must also be required features")
        return values


class ValidatedModelInput(BaseModel):
    """Validated, provenance-carrying values ready for a model adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: PredictiveLayer
    model_id: str
    model_version: str
    symbol: str
    timeframe: str
    source: str
    feature_set_version: str
    feature_schema_version: int
    candle_close_time_utc: datetime
    input_digest: str
    feature_digest: str
    features: dict[str, Decimal]


def validate_model_input(
    snapshot: FeatureSnapshot,
    contract: ModelInputContract,
    *,
    now: datetime | None = None,
) -> ValidatedModelInput:
    """Validate compatibility, readiness, freshness, provenance, and values."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ModelInputValidationError("Validation clock must be timezone-aware")
    instant = instant.astimezone(UTC)

    if snapshot.schema_version != contract.feature_schema_version:
        raise ModelInputValidationError("Feature schema version does not match model contract")
    if snapshot.feature_set_version != contract.feature_set_version:
        raise ModelInputValidationError("Feature set version does not match model contract")
    if snapshot.input_count < contract.minimum_input_count:
        raise ModelInputValidationError("Feature input window is below model minimum")
    if snapshot.candle_close_time_utc.tzinfo is None:
        raise ModelInputValidationError("Feature snapshot timestamp must be timezone-aware")

    age_seconds = (instant - snapshot.candle_close_time_utc.astimezone(UTC)).total_seconds()
    if age_seconds < 0:
        raise ModelInputValidationError("Feature snapshot timestamp is in the future")
    if age_seconds > contract.maximum_snapshot_age_seconds:
        raise ModelInputValidationError("Feature snapshot exceeds model freshness limit")
    if not snapshot.input_digest or not _SHA256_PATTERN.fullmatch(snapshot.input_digest):
        raise ModelInputValidationError("Feature snapshot input provenance is missing or invalid")
    if not _SHA256_PATTERN.fullmatch(snapshot.feature_digest):
        raise ModelInputValidationError("Feature snapshot output digest is invalid")
    serialized_features = json.dumps(
        {"features": snapshot.features, "layer_views": snapshot.layer_views},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    expected_feature_digest = hashlib.sha256(
        serialized_features.encode("utf-8")
    ).hexdigest()
    if snapshot.feature_digest != expected_feature_digest:
        raise ModelInputValidationError("Feature snapshot output digest does not match payload")

    layer_view = snapshot.layer_views.get(contract.layer)
    if layer_view is None:
        raise ModelInputValidationError(f"Snapshot does not contain projection {contract.layer}")
    missing = set(contract.required_features).difference(layer_view)
    if missing:
        raise ModelInputValidationError(
            f"Model contract references unavailable features: {', '.join(sorted(missing))}"
        )

    values: dict[str, Decimal] = {}
    nullable = set(contract.nullable_features)
    for name in contract.required_features:
        raw_value = layer_view[name]
        if raw_value is None:
            if name in nullable:
                continue
            raise ModelInputValidationError(f"Required feature {name} is null")
        try:
            value = Decimal(raw_value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ModelInputValidationError(f"Feature {name} is not a valid decimal") from exc
        if not value.is_finite():
            raise ModelInputValidationError(f"Feature {name} is not finite")
        values[name] = value

    return ValidatedModelInput(
        layer=contract.layer,
        model_id=contract.model_id,
        model_version=contract.model_version,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        source=snapshot.source,
        feature_set_version=snapshot.feature_set_version,
        feature_schema_version=snapshot.schema_version,
        candle_close_time_utc=snapshot.candle_close_time_utc,
        input_digest=snapshot.input_digest,
        feature_digest=snapshot.feature_digest,
        features=values,
    )

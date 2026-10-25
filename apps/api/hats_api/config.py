"""Validated configuration schemas for the HATS API."""
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LayerRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    confidence_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    rules: dict[str, Any] = Field(default_factory=dict)


class RiskRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_risk_pct: float = Field(default=1.0, gt=0.0, le=2.0)
    drawdown_throttle_risk_pct: float = Field(default=0.5, gt=0.0, le=1.0)
    daily_loss_limit_pct: float = Field(default=2.0, gt=0.0, le=5.0)
    rolling_equity_drawdown_trigger_pct: float = Field(
        default=5.0, gt=0.0, le=25.0)
    stop_loss_pips: float = Field(default=20.0, gt=0.0, le=1000.0)
    take_profit_r_multiple: float = Field(default=2.0, gt=0.0, le=20.0)
    max_open_positions: int = Field(default=3, ge=1, le=20)
    max_total_risk_pct: float = Field(default=2.0, gt=0.0, le=5.0)
    daily_reset_timezone: str = "UTC"
    execution_mode: str = "paper"
    limit_entry_expiry_seconds: int = Field(default=900, ge=30, le=86400)

    @model_validator(mode="after")
    def validate_cross_fields(self):
        if self.drawdown_throttle_risk_pct > self.default_risk_pct:
            raise ValueError(
                "Drawdown-throttle risk cannot exceed default risk")
        if self.execution_mode not in {"paper", "live"}:
            raise ValueError("execution_mode must be paper or live")
        return self


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC))
    layer1: LayerRules = Field(default_factory=lambda: LayerRules(rules={"regimes": [
                               "trend", "range", "high_volatility", "uncertain"], "bias_horizons": ["1h", "4h", "1d"]}))
    layer2: LayerRules = Field(default_factory=lambda: LayerRules(
        rules={"phases": ["expansion", "retracement", "consolidation", "transition"]}))
    layer3: LayerRules = Field(default_factory=lambda: LayerRules(rules={"setups": [
                               "QML", "FVG", "CRT", "SBI", "SLR"], "entry_order_type": "limit", "market_order_fallback": False}))
    layer4: RiskRules = Field(default_factory=RiskRules)


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    proposed_config: SystemConfig


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=8, max_length=80)
    confirmation_phrase: str

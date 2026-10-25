"""Plug-in contract for market-data provider adapters.

Concrete adapters translate provider-specific timestamps, symbols, revisions, and
session conventions into canonical CandleEvent objects before returning them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from hats_api.market_data import CandleEvent


@runtime_checkable
class MarketDataProvider(Protocol):
    """Provider interface independent of vendor SDKs and transport protocols."""

    @property
    def provider_name(self) -> str:
        """Stable source identifier written onto each canonical candle."""
        ...

    @property
    def timestamp_convention(self) -> str:
        """Document whether vendor timestamps mark candle open, close, or another instant."""
        ...

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time_utc: datetime,
        end_time_utc: datetime,
    ) -> Sequence[CandleEvent]:
        """Return canonical candles for a bounded UTC interval."""
        ...

    def health(self) -> dict[str, object]:
        """Return adapter connectivity, last-success time, and provider error details."""
        ...

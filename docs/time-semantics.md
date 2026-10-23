# Time, sessions and candle semantics

Correct timing must not depend on the physical location of the broker, OHLCV provider, prop firm, developer or deployment host.

- Store event instants as UTC-aware timestamps. Preserve the source timestamp, source zone/offset, ingestion time and normalized UTC value.
- Use IANA time-zone identifiers such as America/New_York for DST-aware wall-clock schedules. Never hard-code a fixed offset for a DST-observing region.
- The daily risk reset boundary is an explicit policy, not the server's local midnight.
- Synchronize deployment clocks and monitor skew. Block new entries if clock health exceeds a configured tolerance.
- Broker server time is not assumed to be UTC. Each adapter must declare timestamp semantics and conversion rules.
- Distinguish candle open, candle close, forming bar and closed bar. Closed-bar models must not consume incomplete candles.
- Do not silently interpolate missing or out-of-order OHLC bars. Emit a quality event and apply a fail-closed policy.
- Keep bid, ask and mid prices distinct. Separate proposed entry/SL/TP from actual fills and broker-confirmed protection.
- Higher-timeframe aggregation needs explicit anchoring, session/DST rules and missing-bar behavior.
- For repeated or nonexistent local times during DST transitions, require explicit source offset or reject ambiguity.

Every provider adapter must document timestamp format, candle open/close convention, trading sessions/holidays, DST behavior, symbol mapping, heartbeat/data-age limits, sequence ordering and duplicate/revision semantics. GET /api/time/now demonstrates IANA conversion but is not a broker clock validator.

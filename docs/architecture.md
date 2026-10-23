# Architecture baseline

Layer 1 predicts environment/regime. Layer 2 predicts phase eligibility. Layer 3 produces an entry proposal, never a broker command. Layer 4 is deterministic risk authorization and has absolute veto authority. Layer 3B/Sentinel is intentionally absent from the current pipeline and can be added later as an asynchronous component.

The broker adapter must accept only an authorized command produced after Layer 4 checks. This scaffold has no broker execution implementation. Paper mode is the default. Unfilled limit entries expire; market-order fallback is prohibited. Protective exits are separate from entry-order type and should use supported broker protection mechanisms where possible.

## Frontend configuration lifecycle
1. Load active config/version.
2. Edit typed settings in the frontend.
3. Backend validates a draft against the expected active version.
4. UI shows a digest and requires the user to type APPLY CONFIG.
5. Backend rechecks the version, activates the new config and records an audit event.
6. Stale drafts return a conflict and must be reviewed again.

The initial backend uses in-memory state. Production requires PostgreSQL transactions, durable configuration history/audit, authentication, authorization, secret management and rollback. Layer 1–3 rule JSON is data only; model-specific schemas and compatibility checks must be implemented before live use.

Fail closed for new entries if market data, account/risk state or required model output is stale/unknown. Unknown broker order state is unresolved, not failed; reconcile before retrying. Pausing strategy means disable new entries, not abandon positions or cancel protective orders. Daily loss lockout must persist across restart in production.

Planned boundaries: apps/web (control plane), apps/api (configuration/orchestration), packages/contracts, packages/market-data, packages/model-adapters, packages/broker-adapters, crates/hats-risk (Rust deterministic risk), tests (unit/contract/integration/property/end-to-end). Start as a modular monolith. PostgreSQL is durable source of truth; cache/event infrastructure is not authoritative.

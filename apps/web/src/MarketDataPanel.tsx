import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Database, RefreshCw, WifiOff } from "lucide-react";

type Health = {
  status: string;
  latest_candle_at_utc: string | null;
  age_seconds: number | null;
  max_staleness_seconds: number;
  trading_input_eligible: boolean;
  reason: string;
};

type Candle = {
  schema_version: number;
  symbol: string;
  timeframe: string;
  open_time_utc: string;
  close_time_utc: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string | null;
  is_closed: boolean;
  source: string;
  sequence: number | null;
  source_timestamp: string | null;
  source_timezone: string | null;
  ingested_at: string;
};

type QualityEvent = {
  id: number;
  event_at: string;
  symbol: string;
  timeframe: string;
  source: string;
  event_type: string;
  severity: string;
  details: Record<string, unknown>;
};

type Props = { apiBaseUrl: string };

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "5h", "12h", "1d"];
const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"];

function utc(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-GB", {
    timeZone: "UTC",
    timeZoneName: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ageLabel(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return Math.round(seconds) + "s";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m " + Math.floor(seconds % 60) + "s";
  return Math.floor(seconds / 3600) + "h " + Math.floor((seconds % 3600) / 60) + "m";
}

function readable(value: string): string {
  return value.replace(/_/g, " ");
}

export default function MarketDataPanel({ apiBaseUrl }: Props) {
  const [health, setHealth] = useState<Health | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [events, setEvents] = useState<QualityEvent[]>([]);
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("1h");
  const [limit, setLimit] = useState("100");
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const base = apiBaseUrl.replace(/\/$/, "");
    try {
      const [healthResponse, candleResponse, qualityResponse] = await Promise.all([
        fetch(base + "/api/market-data/health"),
        fetch(base + "/api/market-data/candles?" + new URLSearchParams({
          symbol,
          timeframe,
          limit,
        })),
        fetch(base + "/api/market-data/quality?limit=100"),
      ]);
      if (!healthResponse.ok || !candleResponse.ok || !qualityResponse.ok) {
        const failed = [healthResponse, candleResponse, qualityResponse].find((r) => !r.ok);
        throw new Error("Market-data API request failed" + (failed ? " (HTTP " + failed.status + ")" : "."));
      }
      const [healthData, candleData, qualityData] = await Promise.all([
        healthResponse.json() as Promise<Health>,
        candleResponse.json() as Promise<{ candles: Candle[] }>,
        qualityResponse.json() as Promise<{ events: QualityEvent[] }>,
      ]);
      setHealth(healthData);
      setCandles(candleData.candles ?? []);
      setEvents([...(qualityData.events ?? [])].reverse());
      setLastRefresh(new Date().toISOString());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load market-data status.");
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, symbol, timeframe, limit]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const qualityErrors = events.filter((event) => event.severity === "error").length;
  const healthClass = health?.status === "ok" ? "good" : health?.status === "degraded" ? "warning" : "muted";

  return (
    <div className="market-data-view">
      <div className="panel-title-row">
        <div>
          <h2>Market-data observability</h2>
          <p className="sub">Live API reads from persisted candles and quality events. No provider is connected.</p>
        </div>
        <button className="secondary" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={loading ? "spin" : ""} /> {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <div className="market-alert error"><AlertTriangle /><span>{error}</span><button className="secondary compact" onClick={() => void refresh()}>Retry</button></div>}

      <div className="market-banner">
        <Database />
        <div>
          <b>Ingestion API available; provider integration pending</b>
          <p>The backend can store canonical candles submitted by an internal adapter or test client. No vendor feed or broker connection is configured.</p>
        </div>
        <span className="pill">NO PROVIDER</span>
      </div>

      <div className="market-health-grid">
        <article className="market-metric">
          <small>Ingestion status</small>
          <strong className={healthClass}>{health ? readable(health.status) : "Unknown"}</strong>
          <p>{health?.reason ?? "Waiting for market-data health response."}</p>
        </article>
        <article className="market-metric">
          <small>Latest ingested candle close · UTC</small>
          <strong className="metric-date">{utc(health?.latest_candle_at_utc)}</strong>
          <p>Age: {ageLabel(health?.age_seconds ?? null)} · global across stored symbols and timeframes</p>
        </article>
        <article className="market-metric">
          <small>Recent quality errors</small>
          <strong className={qualityErrors > 0 ? "warning" : "good"}>{qualityErrors}</strong>
          <p>From the latest 100 recorded events</p>
        </article>
        <article className="market-metric">
          <small>Strategy input eligibility</small>
          <strong className="warning">Not authorized here</strong>
          <p>Preliminary API flag: {health ? (health.trading_input_eligible ? "eligible" : "not eligible") : "unknown"}. This is not a Layer 4 risk decision.</p>
        </article>
      </div>

      <section className="market-section">
        <div className="market-section-head">
          <div><h3>Stored candles</h3><p className="sub">Times are rendered in UTC. Results are ordered by candle open time.</p></div>
          <div className="market-filters">
            <label><span>Symbol</span><select value={symbol} onChange={(event) => setSymbol(event.target.value)}>{SYMBOLS.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label><span>Timeframe</span><select value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>{TIMEFRAMES.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label><span>Rows</span><select value={limit} onChange={(event) => setLimit(event.target.value)}>{["50", "100", "250", "500", "1000"].map((item) => <option key={item}>{item}</option>)}</select></label>
          </div>
        </div>
        {candles.length === 0 ? (
          <div className="market-empty"><WifiOff /><b>No candles returned for {symbol} · {timeframe}</b><p>Once a provider adapter or test client ingests canonical candles, they will appear here.</p></div>
        ) : (
          <div className="market-table-wrap">
            <table className="market-table">
              <thead><tr><th>Open time · UTC</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>Bar</th><th>Source</th></tr></thead>
              <tbody>{candles.map((candle) => (
                <tr key={candle.source + candle.open_time_utc}>
                  <td><time>{utc(candle.open_time_utc)}</time></td>
                  <td>{candle.open}</td><td>{candle.high}</td><td>{candle.low}</td><td>{candle.close}</td>
                  <td>{candle.volume ?? "—"}</td>
                  <td><span className={candle.is_closed ? "bar-state closed" : "bar-state forming"}>{candle.is_closed ? "Closed" : "Forming"}</span></td>
                  <td>{candle.source}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <p className="market-caption">{candles.length} candle(s) returned · max {Number(limit).toLocaleString()} requested</p>
      </section>

      <section className="market-section">
        <div className="market-section-head">
          <div><h3>Data-quality events</h3><p className="sub">Newest events first; event details remain visible for investigation.</p></div>
          <span className="version-tag">{events.length} loaded</span>
        </div>
        {events.length === 0 ? (
          <div className="market-empty compact-empty"><CheckCircle2 /><b>No quality events returned</b><p>Events will appear when the ingestion service records duplicate, stale, out-of-order, or invalid-timestamp conditions.</p></div>
        ) : (
          <div className="quality-list">{events.map((event) => (
            <article className="quality-event" key={event.id}>
              <div className="quality-event-top">
                <span className={"severity " + event.severity}>{event.severity}</span>
                <b>{readable(event.event_type)}</b>
                <time>{utc(event.event_at)}</time>
              </div>
              <div className="quality-meta"><span>{event.symbol} · {event.timeframe}</span><span>Source: {event.source}</span><span>Event #{event.id}</span></div>
              <details><summary>Inspect event details</summary><pre>{JSON.stringify(event.details, null, 2)}</pre></details>
            </article>
          ))}</div>
        )}
      </section>

      <section className="market-endpoints">
        <div className="market-section-head"><div><h3>Connected API endpoints</h3><p className="sub">This panel reads from these backend routes.</p></div><span className="version-tag">REST</span></div>
        <div className="endpoint-row"><span className="http-method get">GET</span><code>/api/market-data/health</code><span>Freshness and preliminary health</span></div>
        <div className="endpoint-row"><span className="http-method get">GET</span><code>/api/market-data/candles</code><span>Symbol, timeframe, and limit filters</span></div>
        <div className="endpoint-row"><span className="http-method get">GET</span><code>/api/market-data/quality</code><span>Recorded quality events</span></div>
        <div className="endpoint-row"><span className="http-method post">POST</span><code>/api/market-data/candles</code><span>Internal ingestion contract; not exposed as a manual UI action</span></div>
      </section>
      <div className="market-footnote"><Clock3 /><span>Auto-refreshes every 30 seconds while this panel is open. Last successful refresh: {utc(lastRefresh)}. API health and candle freshness are not evidence of provider connectivity, model readiness, or permission to trade.</span></div>
    </div>
  );
}

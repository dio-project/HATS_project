import { useCallback, useEffect, useState } from "react";
import { Activity, Clock3, ShieldCheck } from "lucide-react";

type SystemStatus = {
  execution_mode: string;
  pipeline: string[];
  layer3b_enabled: boolean;
  broker_connected: boolean;
  trading_enabled: boolean;
  note: string;
};

type ApiTime = {
  utc: string;
  timezone: string;
  local: string;
  unix_ms: number;
};

type Props = { apiBaseUrl: string };

const TIMEZONES = ["UTC", "Africa/Lagos", "Europe/London", "America/New_York", "Asia/Tokyo"];
const STAGE_LABELS: Record<string, string> = {
  market_data: "Market data",
  layer1: "Layer 1 · Environment",
  layer2: "Layer 2 · Phase filter",
  layer3: "Layer 3 · Entry proposal",
  layer4_risk: "Layer 4 · Deterministic risk",
};

function formatUtc(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", {
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

export default function SystemStatusPanel({ apiBaseUrl }: Props) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [apiTime, setApiTime] = useState<ApiTime | null>(null);
  const [timezone, setTimezone] = useState("UTC");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const base = apiBaseUrl.replace(/\/$/, "");
    try {
      const [statusResponse, timeResponse] = await Promise.all([
        fetch(base + "/api/system/status"),
        fetch(base + "/api/time/now?" + new URLSearchParams({ timezone_name: timezone })),
      ]);
      if (!statusResponse.ok || !timeResponse.ok) {
        const failed = [statusResponse, timeResponse].find((response) => !response.ok);
        throw new Error("System status request failed" + (failed ? " (HTTP " + failed.status + ")" : "."));
      }
      const [statusData, timeData] = await Promise.all([
        statusResponse.json() as Promise<SystemStatus>,
        timeResponse.json() as Promise<ApiTime>,
      ]);
      setStatus(statusData);
      setApiTime(timeData);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load system status.");
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, timezone]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return (
    <div className="panel system-status-panel">
      <div className="panel-title-row">
        <div><h2>System status & time</h2><p className="sub">Values below are read from the backend status and time APIs.</p></div>
        <button className="secondary" disabled={loading} onClick={() => void refresh()}><Activity /> {loading ? "Refreshing…" : "Refresh status"}</button>
      </div>
      {error && <div className="alert error"><span>{error}</span><button className="secondary compact" onClick={() => void refresh()}>Retry</button></div>}
      {status ? (
        <>
          <div className="system-flags">
            <div><small>Execution mode</small><b>{status.execution_mode.toUpperCase()}</b></div>
            <div><small>Broker connection</small><b className={status.broker_connected ? "good" : "warning"}>{status.broker_connected ? "Connected" : "Not connected"}</b></div>
            <div><small>Trading authorization</small><b className={status.trading_enabled ? "good" : "warning"}>{status.trading_enabled ? "Enabled" : "Disabled"}</b></div>
            <div><small>Layer 3B / Sentinel</small><b>{status.layer3b_enabled ? "Enabled" : "Excluded"}</b></div>
          </div>
          <h3>Backend-reported pipeline</h3>
          <div className="pipeline-list">{status.pipeline.map((stage, index) => (
            <div className="pipeline-row" key={stage}>
              <b>{String(index + 1).padStart(2, "0")} · {STAGE_LABELS[stage] ?? stage}</b>
              <span>{stage === "layer4_risk" ? "Deterministic veto authority · implementation pending" : stage === "market_data" ? "Canonical ingestion available · provider adapter pending" : "Contract/inference integration pending"}</span>
            </div>
          ))}</div>
          <p className="note">{status.note}</p>
        </>
      ) : !error ? <p className="sub">Loading backend status…</p> : null}
      <div className="api-time-panel">
        <div className="api-time-heading"><Clock3 /><div><h3>Backend clock</h3><p className="sub">The backend timestamp is authoritative for system events; display times are explicit.</p></div></div>
        <label className="field"><span>Display time zone</span><select value={timezone} onChange={(event) => setTimezone(event.target.value)}>{TIMEZONES.map((zone) => <option key={zone}>{zone}</option>)}</select></label>
        <div className="api-time-grid">
          <div><small>UTC</small><b>{formatUtc(apiTime?.utc)}</b></div>
          <div><small>{timezone}</small><b>{apiTime ? new Date(apiTime.local).toLocaleString("en-GB", { timeZone: timezone, timeZoneName: "short", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}</b></div>
        </div>
        <p className="market-caption">Unix time (ms): {apiTime?.unix_ms ?? "—"} · Refreshes every 30 seconds.</p>
      </div>
      <div className="system-safety-note"><ShieldCheck /><span>Backend status is informational. It does not activate trading, connect a broker, or replace Layer 4 authorization.</span></div>
    </div>
  );
}

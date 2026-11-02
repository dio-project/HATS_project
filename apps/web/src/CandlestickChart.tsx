import { useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, type CandlestickData, type Time } from "lightweight-charts";

type Candle = { open_time_utc: string; open: string; high: string; low: string; close: string; source: string };
type Props = { candles: Candle[]; source: string; dark: boolean };
type Ohlc = { open: string; high: string; low: string; close: string };
const price = (value: number) => value.toFixed(5);

export default function CandlestickChart({ candles, source, dark }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRef = useRef<ReturnType<ReturnType<typeof createChart>["addSeries"]> | null>(null);
  const [hover, setHover] = useState<Ohlc | null>(null);
  const data = useMemo(() => {
    const rows = new Map<number, CandlestickData<Time>>();
    for (const candle of candles) {
      if (source !== "all" && candle.source !== source) continue;
      const time = Math.floor(Date.parse(candle.open_time_utc) / 1000) as Time;
      if (!Number.isFinite(time)) continue;
      rows.set(Number(time), { time, open: Number(candle.open), high: Number(candle.high), low: Number(candle.low), close: Number(candle.close) });
    }
    return [...rows.values()].sort((a, b) => Number(a.time) - Number(b.time));
  }, [candles, source]);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      width: Math.max(element.clientWidth, 320), height: 390,
      layout: { background: { type: ColorType.Solid, color: dark ? "#111a26" : "#ffffff" }, textColor: dark ? "#a9b7c8" : "#526174", fontFamily: "DM Mono, monospace", fontSize: 11 },
      grid: { vertLines: { color: dark ? "#202d3c" : "#edf0f4" }, horzLines: { color: dark ? "#202d3c" : "#edf0f4" } },
      rightPriceScale: { borderColor: dark ? "#344256" : "#dce2ea" },
      timeScale: { borderColor: dark ? "#344256" : "#dce2ea", timeVisible: true, secondsVisible: false, rightOffset: 5 },
      crosshair: { mode: CrosshairMode.Normal }, handleScroll: true, handleScale: true
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#16a879", downColor: "#e05b68", borderUpColor: "#16a879", borderDownColor: "#e05b68",
      wickUpColor: "#16a879", wickDownColor: "#e05b68", priceLineVisible: true
    });
    chartRef.current = chart;
    seriesRef.current = series;
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width;
      if (width && width > 0) chart.applyOptions({ width: Math.floor(width) });
    });
    observer.observe(element);
    chart.subscribeCrosshairMove(param => {
      if (!param.time) { setHover(null); return; }
      const point = param.seriesData.get(series) as CandlestickData<Time> | undefined;
      setHover(point ? { open: price(point.open), high: price(point.high), low: price(point.low), close: price(point.close) } : null);
    });
    return () => { observer.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, [dark]);

  useEffect(() => {
    if (!seriesRef.current || !chartRef.current) return;
    seriesRef.current.setData(data);
    if (data.length) chartRef.current.timeScale().fitContent();
    setHover(null);
  }, [data]);

  const latest = data[data.length - 1];
  return <section className="candle-chart-panel">
    <div className="candle-chart-heading"><div><h3>Price chart</h3><p className="sub">OHLC candles · UTC · scroll to pan, wheel/pinch to zoom</p></div><span className="version-tag">{data.length} bars</span></div>
    <div className="candle-ohlc" aria-live="polite">
      <span>O <b>{hover?.open ?? (latest ? price(latest.open) : "—")}</b></span>
      <span>H <b>{hover?.high ?? (latest ? price(latest.high) : "—")}</b></span>
      <span>L <b>{hover?.low ?? (latest ? price(latest.low) : "—")}</b></span>
      <span>C <b>{hover?.close ?? (latest ? price(latest.close) : "—")}</b></span>
    </div>
    <div ref={host} className="candle-chart" role="img" aria-label="Interactive market candlestick chart" />
    <p className="market-caption">Plotted from stored canonical OHLC values. Select a source to avoid mixing feeds.</p>
  </section>;
}

/* Plotly wrappers tuned for the Liquid Glass Dark palette, plus SVG sparklines. */

import { el, svg } from "./ui.js";
import { num } from "./format.js";

const COLORS = {
  accent: "#6fa8ff",
  accentSoft: "rgba(111, 168, 255, 0.18)",
  mint: "#31e0a0",
  mintSoft: "rgba(49, 224, 160, 0.16)",
  red: "#ff5c7a",
  amber: "#ffc65c",
  violet: "#a78bfa",
  grid: "rgba(255, 255, 255, 0.06)",
  text: "#a8b4d0",
  faint: "#6d7a99",
};

export function plotlyReady() {
  return typeof window !== "undefined" && Boolean(window.Plotly);
}

// Plotly falls back to a −1…1 axis for a series with zero span, which would hide
// the real level entirely when snapshots carry an unchanged price.
function paddedRange(values) {
  const nums = values.filter((value) => Number.isFinite(value));
  if (!nums.length) return undefined;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  if (max > min) return undefined;
  const pad = Math.abs(min) * 0.01 || 1e-9;
  return [min - pad, max + pad];
}

function baseLayout(overrides = {}) {
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, system-ui, sans-serif", color: COLORS.text, size: 11 },
    margin: { l: 46, r: 16, t: 12, b: 30 },
    showlegend: false,
    hovermode: "x unified",
    hoverlabel: {
      bgcolor: "rgba(12,18,36,0.95)",
      bordercolor: "rgba(255,255,255,0.12)",
      font: { color: "#eaf0ff", size: 11, family: "JetBrains Mono, monospace" },
    },
    xaxis: {
      gridcolor: COLORS.grid,
      zeroline: false,
      linecolor: "rgba(255,255,255,0.06)",
      tickfont: { color: COLORS.faint, size: 10 },
      fixedrange: true,
    },
    yaxis: {
      gridcolor: COLORS.grid,
      zeroline: false,
      linecolor: "rgba(255,255,255,0.06)",
      tickfont: { color: COLORS.faint, size: 10 },
      fixedrange: true,
    },
    ...overrides,
  };
}

function render(node, traces, layout, config = {}) {
  if (!node) return;
  if (!plotlyReady()) {
    node.replaceChildren(
      el("div", {
        class: "empty",
        style: { padding: "32px 16px" },
      }, el("p", { class: "muted", text: "Chart engine unavailable — data is still shown in tables." })),
    );
    return;
  }
  const options = {
    displayModeBar: false,
    responsive: true,
    scrollZoom: false,
    doubleClick: "reset",
    ...config,
  };
  // Plotly.react reuses an existing plot but leaves unrelated children (such as
  // the loading skeleton) in place, so drop them on first paint.
  const existing = node.firstElementChild;
  if (!existing || !existing.classList.contains("js-plotly-plot")) node.replaceChildren();
  window.Plotly.react(node, traces, baseLayout(layout), options);
}

export function lineChart(node, points, { x = "ts", y = "price", name = "Price", color = COLORS.accent, fill = true, format = "usd" } = {}) {
  const rows = (points || []).filter((p) => p[x]);
  if (!rows.length) {
    renderEmpty(node);
    return;
  }
  const trace = {
    x: rows.map((p) => p[x]),
    y: rows.map((p) => num(p[y])),
    type: "scatter",
    mode: "lines",
    name,
    line: { color, width: 2, shape: "spline", smoothing: 0.5 },
    fill: fill ? "tozeroy" : "none",
    fillcolor: fill ? "rgba(111, 168, 255, 0.12)" : undefined,
    hovertemplate: format === "usd" ? "$%{y:.6~f}<extra></extra>" : "%{y:.2f}<extra></extra>",
  };
  render(node, [trace], {
    margin: { l: 56, r: 16, t: 12, b: 28 },
    yaxis: {
      gridcolor: COLORS.grid,
      zeroline: false,
      tickfont: { color: COLORS.faint, size: 10 },
      tickprefix: format === "usd" ? "$" : "",
      range: paddedRange(trace.y),
      fixedrange: true,
    },
  });
}

export function duelChart(node, points, { priceKey = "price", volumeKey = "volume_h1" } = {}) {
  const rows = (points || []).filter((p) => p.ts);
  if (!rows.length) {
    renderEmpty(node);
    return;
  }
  const traces = [
    {
      x: rows.map((p) => p.ts),
      y: rows.map((p) => num(p[volumeKey])),
      type: "bar",
      name: "Volume 1h",
      marker: { color: "rgba(111, 168, 255, 0.22)", line: { width: 0 } },
      yaxis: "y2",
      hovertemplate: "Vol $%{y:,.0f}<extra></extra>",
    },
    {
      x: rows.map((p) => p.ts),
      y: rows.map((p) => num(p[priceKey])),
      type: "scatter",
      mode: "lines",
      name: "Price",
      line: { color: COLORS.mint, width: 2, shape: "spline", smoothing: 0.4 },
      hovertemplate: "$%{y:.8~f}<extra></extra>",
      yaxis: "y",
    },
  ];
  render(node, traces, {
    margin: { l: 56, r: 12, t: 12, b: 28 },
    yaxis: {
      domain: [0.32, 1],
      gridcolor: COLORS.grid,
      zeroline: false,
      tickfont: { color: COLORS.faint, size: 10 },
      tickprefix: "$",
      range: paddedRange(traces[1].y),
      fixedrange: true,
    },
    yaxis2: {
      domain: [0, 0.22],
      gridcolor: "transparent",
      zeroline: false,
      showticklabels: false,
      range: paddedRange(traces[0].y),
      fixedrange: true,
    },
  });
}

export function areaChart(node, points, { x = "day", y = "equity", color = COLORS.mint, prefix = "$" } = {}) {
  const rows = (points || []).filter((p) => p[x] != null);
  if (!rows.length) {
    renderEmpty(node);
    return;
  }
  const trace = {
    x: rows.map((p) => p[x]),
    y: rows.map((p) => num(p[y])),
    type: "scatter",
    mode: "lines+markers",
    line: { color, width: 2, shape: "spline", smoothing: 0.4 },
    marker: { size: 4, color },
    fill: "tozeroy",
    fillcolor: color === COLORS.mint ? "rgba(49, 224, 160, 0.1)" : "rgba(111, 168, 255, 0.1)",
    hovertemplate: `${prefix}%{y:,.4~f}<extra></extra>`,
  };
  render(node, [trace], {
    yaxis: {
      gridcolor: COLORS.grid,
      zeroline: false,
      tickprefix: prefix,
      tickfont: { color: COLORS.faint, size: 10 },
      range: paddedRange(trace.y),
      fixedrange: true,
    },
  });
}

export function barChart(node, labels, values, { color = COLORS.accent, prefix = "", suffix = "" } = {}) {
  if (!labels || !labels.length) {
    renderEmpty(node);
    return;
  }
  const trace = {
    x: labels,
    y: values.map((v) => num(v)),
    type: "bar",
    marker: {
      color: "rgba(111, 168, 255, 0.55)",
      line: { color, width: 1 },
    },
    hovertemplate: `${prefix}%{y:,~f}${suffix}<extra></extra>`,
  };
  render(node, [trace], {
    margin: { l: 44, r: 12, t: 12, b: 34 },
    xaxis: { gridcolor: "transparent", tickfont: { color: COLORS.faint, size: 10 }, fixedrange: true },
    yaxis: { gridcolor: COLORS.grid, zeroline: false, tickfont: { color: COLORS.faint, size: 10 }, fixedrange: true },
    bargap: 0.45,
  });
}

export function donutChart(node, items, { centerLabel = "", centerValue = "" } = {}) {
  const rows = (items || []).filter((item) => num(item.value) > 0);
  if (!rows.length) {
    renderEmpty(node, centerLabel ? `${centerLabel} unavailable` : "No allocation yet");
    return;
  }
  const trace = {
    labels: rows.map((item) => item.label),
    values: rows.map((item) => num(item.value)),
    type: "pie",
    hole: 0.72,
    sort: false,
    direction: "clockwise",
    textinfo: "none",
    marker: {
      colors: rows.map((item) => item.color || COLORS.accent),
      line: { color: "rgba(5,8,18,0.9)", width: 2 },
    },
    hovertemplate: "%{label}: $%{value:,.2f} (%{percent})<extra></extra>",
  };
  render(
    node,
    [trace],
    {
      margin: { l: 8, r: 8, t: 8, b: 8 },
      showlegend: true,
      legend: { orientation: "h", font: { size: 10, color: COLORS.text }, y: -0.08 },
      annotations: [
        {
          text: `<b style="font-family:JetBrains Mono,monospace;font-size:18px;color:#eaf0ff">${centerValue}</b><br><span style="font-size:9px;letter-spacing:.18em;color:#6d7a99">${centerLabel}</span>`,
          showarrow: false,
          font: { color: COLORS.text },
        },
      ],
    },
    { displayModeBar: false },
  );
}

export function renderEmpty(node, message = "Waiting for data") {
  if (!node) return;
  node.replaceChildren(
    el(
      "div",
      { class: "empty", style: { padding: "36px 16px" } },
      el("div", { class: "empty-icon", text: "◌" }),
      el("p", { class: "muted", text: message }),
    ),
  );
}

export function resize(node) {
  if (plotlyReady() && node && node.data) window.Plotly.Plots.resize(node);
}

/* Lightweight inline sparkline (no Plotly instance per tile). */
export function sparkline(values, { color = COLORS.accent, width = 92, height = 30 } = {}) {
  const nums = (values || []).map((v) => num(v)).filter((v) => Number.isFinite(v));
  const node = svg("svg", {
    class: "stat-spark",
    viewBox: `0 0 ${width} ${height}`,
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  if (nums.length < 2) return node;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const step = width / (nums.length - 1);
  const points = nums.map((value, index) => {
    const x = index * step;
    const y = height - 3 - ((value - min) / span) * (height - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const id = `spark-${Math.random().toString(36).slice(2, 8)}`;
  node.append(
    svg(
      "defs",
      {},
      svg(
        "linearGradient",
        { id, x1: "0", y1: "0", x2: "0", y2: "1" },
        svg("stop", { offset: "0", "stop-color": color, "stop-opacity": "0.35" }),
        svg("stop", { offset: "1", "stop-color": color, "stop-opacity": "0" }),
      ),
    ),
    svg("polygon", {
      points: `0,${height} ${points.join(" ")} ${width},${height}`,
      fill: `url(#${id})`,
    }),
    svg("polyline", {
      points: points.join(" "),
      fill: "none",
      stroke: color,
      "stroke-width": "1.6",
      "stroke-linejoin": "round",
      "stroke-linecap": "round",
    }),
  );
  return node;
}

export { COLORS };

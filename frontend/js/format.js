/* Formatting helpers. Every number rendered in the UI is paper/simulated. */

const moneyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const moneyFmt4 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const compactFmt = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 2,
});

export function num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function money(value, digits = 2) {
  const n = num(value);
  if (digits === 4) return moneyFmt4.format(n);
  return moneyFmt.format(n);
}

export function signedMoney(value, digits = 2) {
  const n = num(value);
  const text = money(Math.abs(n), digits);
  if (n > 0) return `+${text}`;
  if (n < 0) return `-${text}`;
  return text;
}

export function compact(value) {
  return compactFmt.format(num(value));
}

export function usdCompact(value) {
  const n = num(value);
  if (Math.abs(n) >= 1_000_000) return `$${compact(n)}`;
  if (Math.abs(n) >= 1_000) return `$${compact(n)}`;
  return `$${n.toFixed(2)}`;
}

export function price(value) {
  const n = num(value);
  if (n === 0) return "$0.00";
  if (n >= 1) return money(n, 4);
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  if (n >= 0.0001) return `$${n.toFixed(6)}`;
  return `$${n.toExponential(2)}`;
}

export function pct(value, digits = 2) {
  const n = num(value);
  return `${n.toFixed(digits)}%`;
}

export function signedPct(value, digits = 2) {
  const n = num(value);
  const text = `${Math.abs(n).toFixed(digits)}%`;
  if (n > 0) return `+${text}`;
  if (n < 0) return `-${text}`;
  return text;
}

export function ratio(value) {
  const n = num(value);
  return n.toFixed(2);
}

export function int(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(num(value));
}

export function signClass(value) {
  const n = num(value);
  if (n > 0) return "pos";
  if (n < 0) return "neg";
  return "neutral";
}

export function timeAgo(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function clock(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.toLocaleDateString([], { month: "short", day: "2-digit" })} ${d.toLocaleTimeString(
    [],
    { hour: "2-digit", minute: "2-digit" },
  )}`;
}

export function durationMs(value) {
  const ms = num(value);
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function countdown(iso) {
  if (!iso) return "—";
  const delta = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (!Number.isFinite(delta)) return "—";
  if (delta <= 0) return "due";
  if (delta < 60) return `${delta}s`;
  return `${Math.round(delta / 60)}m ${delta % 60}s`;
}

export function ageMinutes(value) {
  const n = num(value);
  if (n < 60) return `${Math.round(n)}m`;
  if (n < 1440) return `${(n / 60).toFixed(1)}h`;
  return `${(n / 1440).toFixed(1)}d`;
}

export function chainLabel(chain) {
  return chain === "bsc" ? "BNB Chain" : chain === "solana" ? "Solana" : chain || "—";
}

export function shortAddress(address, head = 6, tail = 4) {
  if (!address) return "—";
  if (address.length <= head + tail + 3) return address;
  return `${address.slice(0, head)}…${address.slice(-tail)}`;
}

export function initials(symbol) {
  const s = (symbol || "?").replace(/[^a-zA-Z0-9]/g, "");
  return (s.slice(0, 3) || "?").toUpperCase();
}

export function titleCase(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/(^|[\s_-])([a-z])/g, (_, sep, ch) => `${sep ? " " : ""}${ch.toUpperCase()}`)
    .trim();
}

export function humanizeCode(code) {
  return titleCase(String(code || "").replace(/_/g, " "));
}

export function csv(rows, columns) {
  const escape = (value) => {
    const text = value == null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const header = columns.map((c) => escape(c.label)).join(",");
  const body = rows.map((row) => columns.map((c) => escape(c.value(row))).join(",")).join("\n");
  return `${header}\n${body}`;
}

export function downloadCsv(filename, content) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

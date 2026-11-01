/* Application boot: shell wiring, live stream, badges and the router. */

import { api } from "./api.js";
import { startRouter } from "./router.js";
import { onEvent, startStream } from "./sse.js";
import { refreshAll, refreshHealth, refreshPortfolio, store, subscribe } from "./store.js";
import { clock, countdown } from "./format.js";

const app = document.getElementById("app");
const view = document.getElementById("view");
const scrim = document.getElementById("scrim");
const menuToggle = document.getElementById("menu-toggle");
const refreshBtn = document.getElementById("refresh-btn");
const pageTitle = document.getElementById("page-title");
const pageCrumb = document.getElementById("page-crumb");
const tokenLink = document.getElementById("nav-token-link");

const els = {
  scannerCount: document.getElementById("nav-scanner-count"),
  positionCount: document.getElementById("nav-position-count"),
  notifyCount: document.getElementById("nav-notify-count"),
  topScan: document.getElementById("scan-connection"),
  topScanText: document.getElementById("scan-connection-text"),
  sidebarScan: document.getElementById("sidebar-scan-state"),
  sidebarScanText: document.getElementById("sidebar-scan-text"),
  stream: document.getElementById("stream-connection"),
  streamText: document.getElementById("stream-connection-text"),
};

let noticeCount = 0;
let currentParams = [];
let pollTimer = null;

/* ------------------------------------------------------------------ shell */

function closeMenu() {
  app.classList.remove("nav-open");
  menuToggle.setAttribute("aria-expanded", "false");
}

menuToggle.addEventListener("click", () => {
  const open = app.classList.toggle("nav-open");
  menuToggle.setAttribute("aria-expanded", String(open));
});
scrim.addEventListener("click", closeMenu);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenu();
});

document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", () => {
    if (link.id !== "nav-token-link") closeMenu();
  });
});

refreshBtn.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  try {
    await refreshAll();
    await refreshNotices();
    window.dispatchEvent(new CustomEvent("lab:refresh"));
  } finally {
    setTimeout(() => {
      refreshBtn.disabled = false;
    }, 400);
  }
});

function setConnection(node, textNode, state, text, title) {
  if (!node) return;
  node.classList.remove("live", "offline");
  if (state === "live") node.classList.add("live");
  else if (state === "offline") node.classList.add("offline");
  if (textNode && text != null) textNode.textContent = text;
  if (title) node.title = title;
}

function renderHealth() {
  const health = store.health;
  const scanner = store.scanner;
  if (!health || !scanner) {
    setConnection(els.topScan, els.topScanText, "offline", "Scanner offline", "The API is unreachable.");
    setConnection(els.sidebarScan, els.sidebarScanText, "offline", "Scanner offline");
    return;
  }
  const running = scanner.state === "running";
  const stale = Boolean(scanner.stale);
  const state = !running || stale ? "offline" : "live";
  const label = !running ? "Scanner stopped" : stale ? "Scanner stale" : "Scanner live";
  const title = `Last success ${
    scanner.last_success_at ? clock(scanner.last_success_at) : "never"
  } · next ${scanner.next_scan_at ? countdown(scanner.next_scan_at) : "—"}`;
  setConnection(els.topScan, els.topScanText, state, label, title);
  setConnection(els.sidebarScan, els.sidebarScanText, state, label);
  if (scanner.last_run) {
    els.scannerCount.textContent = String(scanner.last_run.discovered ?? 0);
    els.scannerCount.title = `${scanner.last_run.discovered ?? 0} new pools discovered in the last tick`;
  }
}

function renderPortfolio() {
  if (!store.portfolio) return;
  const open = store.portfolio.open_positions ?? 0;
  const cap = store.portfolio.max_open_positions ?? 3;
  els.positionCount.textContent = `${open}/${cap}`;
  els.positionCount.classList.toggle("hot", open >= cap);
}

function renderStream() {
  const map = {
    live: { cls: "live", text: "Live" },
    connecting: { cls: "", text: "Connecting" },
    offline: { cls: "offline", text: "Reconnecting" },
    unsupported: { cls: "offline", text: "No stream" },
  };
  const entry = map[store.stream] || map.connecting;
  setConnection(els.stream, els.streamText, entry.cls, entry.text, "Server-sent events connection");
}

function renderNotices() {
  if (!els.notifyCount) return;
  els.notifyCount.textContent = String(noticeCount);
  els.notifyCount.classList.toggle("hot", noticeCount > 0);
}

async function refreshNotices() {
  try {
    const payload = await api.notifications(50);
    const counts = payload.status_counts || {};
    noticeCount = (counts.PENDING || 0) + (counts.QUEUED || 0);
    renderNotices();
  } catch {
    /* keep the last known count */
  }
}

function applyRoute(meta) {
  currentParams = meta.params || [];
  pageTitle.textContent = meta.title || "Overview";
  pageCrumb.textContent = meta.crumb || "Desk";
  document.querySelectorAll(".nav-link[data-route]").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === meta.name);
  });
  if (meta.name === "token") {
    document.querySelectorAll(".nav-link").forEach((link) => link.classList.remove("active"));
    if (tokenLink) {
      tokenLink.hidden = false;
      tokenLink.classList.add("active");
      if (currentParams[0]) tokenLink.href = `#/token/${currentParams[0]}`;
    }
  } else if (tokenLink) {
    tokenLink.hidden = true;
  }
  closeMenu();
}

function updateCountdown() {
  const scanner = store.scanner;
  if (!scanner || !els.topScan) return;
  const title = `Last success ${scanner.last_success_at ? clock(scanner.last_success_at) : "never"} · next ${
    scanner.next_scan_at ? countdown(scanner.next_scan_at) : "—"
  }`;
  els.topScan.title = title;
  if (scanner.state === "running" && !scanner.stale && els.topScanText) {
    els.topScanText.textContent = scanner.next_scan_at
      ? `Scanning · ${countdown(scanner.next_scan_at)}`
      : "Scanner live";
  }
}

/* ------------------------------------------------------------------ live */

function bindStream() {
  startStream();
  onEvent("scanner", () => {
    refreshHealth();
    refreshPortfolio();
  });
  onEvent("trade", () => {
    refreshPortfolio();
    window.dispatchEvent(new CustomEvent("lab:trade"));
  });
  onEvent("portfolio", () => refreshPortfolio());
  onEvent("watchlist", () => window.dispatchEvent(new CustomEvent("lab:watchlist")));
  onEvent("notifications", () => refreshNotices());
  onEvent("status", () => refreshHealth());
  onEvent("heartbeat", () => {
    store.lastSync = Date.now();
  });
}

/* ------------------------------------------------------------------ boot */

subscribe((topic) => {
  if (topic === "health") {
    renderHealth();
    renderPortfolio();
    updateCountdown();
  }
  if (topic === "portfolio") renderPortfolio();
  if (topic === "stream") {
    renderStream();
    // Events fired while the stream was down are lost, so resync state after
    // every reconnect instead of waiting for the next trade.
    if (store.stream === "live" && Date.now() - store.lastSync > 15000) {
      refreshAll().then(() => window.dispatchEvent(new CustomEvent("lab:refresh")));
    }
  }
});

startRouter({ view, onChange: applyRoute });

await refreshAll();
await refreshNotices();
renderHealth();
renderPortfolio();
renderStream();
bindStream();
updateCountdown();

setInterval(updateCountdown, 1000);
pollTimer = setInterval(refreshAll, 30000);
window.addEventListener("beforeunload", () => clearInterval(pollTimer));

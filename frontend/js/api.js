/* Typed-ish API client for the paper trading backend. */

const BASE = ((window.LAB_CONFIG && window.LAB_CONFIG.apiBase) || "").replace(/\/+$/, "");
const ADMIN_KEY = "lab.adminToken";

export function getAdminToken() {
  try {
    return sessionStorage.getItem(ADMIN_KEY) || "";
  } catch {
    return "";
  }
}

export function setAdminToken(token) {
  try {
    if (token) sessionStorage.setItem(ADMIN_KEY, token);
    else sessionStorage.removeItem(ADMIN_KEY);
  } catch {
    /* storage unavailable — mutations will simply use the open mode */
  }
}

function headers(body) {
  const out = {};
  if (body) out["Content-Type"] = "application/json";
  const token = getAdminToken();
  if (token) out["X-Admin-Token"] = token;
  const tick = window.LAB_CONFIG && window.LAB_CONFIG.scanToken;
  if (tick) out["X-Scan-Token"] = tick;
  return Object.keys(out).length ? out : undefined;
}

export class ApiError extends Error {
  constructor(message, { code, status, details } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code || "ERROR";
    this.status = status || 0;
    this.details = details || {};
  }
}

function query(params) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request(path, { method = "GET", body, params, signal } = {}) {
  let response;
  try {
    response = await fetch(`${BASE}/api/v1${path}${query(params)}`, {
      method,
      signal,
      headers: headers(body),
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Cannot reach the lab API. Check the connection or API base URL.", {
      code: "NETWORK_ERROR",
    });
  }

  if (response.status === 204) return null;
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const err = payload && payload.error ? payload.error : {};
    throw new ApiError(err.message || `Request failed (${response.status})`, {
      code: err.code || `HTTP_${response.status}`,
      status: response.status,
      details: err.details || {},
    });
  }
  return payload;
}

export const api = {
  base: BASE,

  health: () => request("/health"),
  ready: () => request("/health/ready"),

  scannerStatus: () => request("/scanner/status"),
  scannerRuns: (limit = 20) => request("/scanner/runs", { params: { limit } }),
  scannerStart: () => request("/scanner/start", { method: "POST" }),
  scannerStop: () => request("/scanner/stop", { method: "POST" }),
  scannerTick: () => request("/scanner/tick", { method: "POST" }),

  tokens: (params) => request("/tokens", { params }),
  token: (id) => request(`/tokens/${id}`),
  tokenHistory: (id, params) => request(`/tokens/${id}/history`, { params }),

  watchlist: () => request("/watchlist"),
  addWatchlist: (tokenId) => request("/watchlist", { method: "POST", body: { token_id: tokenId } }),
  removeWatchlist: (tokenId) => request(`/watchlist/${tokenId}`, { method: "DELETE" }),
  watchToken: (tokenId) => request(`/tokens/${tokenId}/watchlist`, { method: "POST" }),
  unwatchToken: (tokenId) => request(`/tokens/${tokenId}/watchlist`, { method: "DELETE" }),

  portfolio: () => request("/portfolio"),
  positions: (params) => request("/portfolio/positions", { params }),
  performance: () => request("/portfolio/performance"),
  equity: (days = 30) => request("/portfolio/equity", { params: { days } }),

  buy: (payload) => request("/paper-trades/buy", { method: "POST", body: payload }),
  sell: (payload) => request("/paper-trades/sell", { method: "POST", body: payload }),
  tradeHistory: (params) => request("/paper-trades/history", { params }),

  strategy: (decisions = 25) => request("/strategies", { params: { decisions } }),
  saveStrategy: (settings) => request("/strategies/settings", { method: "PUT", body: settings }),
  resetStrategy: () => request("/strategies/settings/reset", { method: "POST" }),
  decisions: (limit = 50) => request("/strategies/decisions", { params: { limit } }),

  analytics: (include) => request("/analytics", { params: include ? { include } : undefined }),
  marketAnalytics: () => request("/analytics/market"),
  portfolioAnalytics: () => request("/analytics/portfolio"),

  notifications: (limit = 50) => request("/notifications", { params: { limit } }),
  testNotification: () => request("/notifications/test", { method: "POST" }),
  dispatchNotifications: () => request("/notifications/dispatch", { method: "POST" }),

  settings: () => request("/settings"),
  saveSettings: (payload) => request("/settings", { method: "PUT", body: payload }),

  streamUrl: () => `${BASE}/api/v1/stream`,
};

/* Global, shared state for the shell, the SSE stream and the pages. */

import { api } from "./api.js";

const listeners = new Set();

export const store = {
  health: null,
  scanner: null,
  portfolio: null,
  settings: null,
  stream: "connecting",
  lastEvent: null,
  lastSync: 0,
};

function emit(topic) {
  listeners.forEach((listener) => {
    try {
      listener(topic, store);
    } catch (error) {
      console.error("store listener failed", error);
    }
  });
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function refreshHealth() {
  try {
    const [health, scanner] = await Promise.all([api.health(), api.scannerStatus()]);
    store.health = health;
    store.scanner = scanner;
    store.lastSync = Date.now();
    emit("health");
  } catch (error) {
    store.health = null;
    emit("health");
  }
}

let portfolioRequest = 0;

export async function refreshPortfolio() {
  // Several SSE trade events can land at once; only the newest response may
  // replace state, otherwise an older snapshot can overwrite a fresh one.
  const ticket = ++portfolioRequest;
  try {
    const snapshot = await api.portfolio();
    if (ticket !== portfolioRequest) return;
    store.portfolio = snapshot;
    emit("portfolio");
  } catch {
    if (ticket === portfolioRequest) emit("portfolio");
  }
}

export async function refreshSettings() {
  try {
    store.settings = await api.settings();
    emit("settings");
  } catch {
    emit("settings");
  }
}

export function setStreamState(state) {
  store.stream = state;
  emit("stream");
}

export function noteEvent(event) {
  store.lastEvent = event;
  emit(event && event.type ? event.type : "event");
}

export async function refreshAll() {
  await Promise.allSettled([refreshHealth(), refreshPortfolio()]);
}

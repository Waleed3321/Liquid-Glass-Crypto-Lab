/* Server-Sent Events client with automatic reconnection. */

import { api } from "./api.js";
import { noteEvent, setStreamState } from "./store.js";

const EVENT_TYPES = [
  "status",
  "heartbeat",
  "scanner",
  "trade",
  "watchlist",
  "notifications",
  "portfolio",
];

const handlers = new Map();
let source = null;
let reconnectTimer = null;
let backoff = 2000;

export function onEvent(type, handler) {
  if (!handlers.has(type)) handlers.set(type, new Set());
  handlers.get(type).add(handler);
  return () => handlers.get(type)?.delete(handler);
}

function dispatch(type, payload) {
  noteEvent(payload);
  handlers.get(type)?.forEach((handler) => {
    try {
      handler(payload);
    } catch (error) {
      console.error(`sse handler ${type} failed`, error);
    }
  });
  handlers.get("*")?.forEach((handler) => handler(payload));
}

function connect() {
  if (typeof EventSource === "undefined") {
    setStreamState("unsupported");
    return;
  }
  if (source) source.close();
  setStreamState("connecting");
  try {
    source = new EventSource(api.streamUrl());
  } catch {
    setStreamState("offline");
    scheduleReconnect();
    return;
  }

  source.onopen = () => {
    backoff = 2000;
    setStreamState("live");
  };

  source.onerror = () => {
    setStreamState("offline");
    source.close();
    scheduleReconnect();
  };

  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (event) => {
      let payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch {
        payload = null;
      }
      if (payload) dispatch(type, payload);
    });
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, backoff);
  backoff = Math.min(backoff * 1.6, 30000);
}

export function startStream() {
  connect();
}

export function stopStream() {
  clearTimeout(reconnectTimer);
  if (source) source.close();
  source = null;
}

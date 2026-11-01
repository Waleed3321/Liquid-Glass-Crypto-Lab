/* Hash router. Every page module exports `{ title, crumb, render(ctx) }`. */

import { el, mount } from "./ui.js";

export const ROUTES = [
  { name: "overview", title: "Overview", crumb: "Desk", load: () => import("./pages/overview.js") },
  { name: "scanner", title: "Live Scanner", crumb: "Desk", load: () => import("./pages/scanner.js") },
  { name: "watchlist", title: "Watchlist", crumb: "Desk", load: () => import("./pages/watchlist.js") },
  { name: "portfolio", title: "Paper Portfolio", crumb: "Paper book", load: () => import("./pages/portfolio.js") },
  { name: "positions", title: "Open Positions", crumb: "Paper book", load: () => import("./pages/positions.js") },
  { name: "history", title: "Trade History", crumb: "Paper book", load: () => import("./pages/history.js") },
  { name: "strategy", title: "Strategy Lab", crumb: "Research", load: () => import("./pages/strategy.js") },
  { name: "intelligence", title: "Market Intelligence", crumb: "Research", load: () => import("./pages/intelligence.js") },
  { name: "notifications", title: "Notifications", crumb: "Research", load: () => import("./pages/notifications.js") },
  { name: "settings", title: "Settings", crumb: "Research", load: () => import("./pages/settings.js") },
  { name: "token", title: "Token Details", crumb: "Research", hidden: true, load: () => import("./pages/token.js") },
];

export function parseHash() {
  const raw = (window.location.hash || "#/overview").replace(/^#\/?/, "");
  const [path, search = ""] = raw.split("?");
  const segments = path.split("/").filter(Boolean).map((part) => decodeURIComponent(part));
  const name = segments[0] || "overview";
  return {
    name,
    params: segments.slice(1),
    query: Object.fromEntries(new URLSearchParams(search)),
  };
}

const state = {
  view: null,
  seq: 0,
  controller: null,
  cleanups: [],
  onChange: null,
  title: "",
  crumb: "",
};

export function routeDef(name) {
  return ROUTES.find((route) => route.name === name) || ROUTES[0];
}

export function startRouter({ view, onChange }) {
  state.view = view;
  state.onChange = onChange;
  if (!window.location.hash) window.location.replace("#/overview");
  window.addEventListener("hashchange", () => render());
  render();
}

export function navigate(path) {
  const next = String(path).startsWith("#") ? String(path) : `#/${String(path).replace(/^\/+/, "")}`;
  if (window.location.hash === next) render();
  else window.location.hash = next;
}

export function reload() {
  render();
}

function teardown() {
  if (state.controller) state.controller.abort();
  for (const cleanup of state.cleanups.splice(0)) {
    try {
      cleanup();
    } catch (error) {
      console.error("page cleanup failed", error);
    }
  }
}

function skeleton() {
  return el(
    "div",
    { class: "stack", "aria-busy": "true" },
    el(
      "div",
      { class: "panel glass" },
      el("div", { class: "skeleton skeleton-row", style: { width: "38%" } }),
      el("div", { class: "skeleton skeleton-row", style: { width: "68%" } }),
      el("div", { class: "skeleton skeleton-row", style: { width: "52%" } }),
    ),
    el(
      "div",
      { class: "grid" },
      el("div", { class: "col-4" }, el("div", { class: "skeleton", style: { height: "118px" } })),
      el("div", { class: "col-4" }, el("div", { class: "skeleton", style: { height: "118px" } })),
      el("div", { class: "col-4" }, el("div", { class: "skeleton", style: { height: "118px" } })),
    ),
  );
}

export function errorPanel(error, retry) {
  const code = error && error.code ? String(error.code) : "ERROR";
  return el(
    "div",
    { class: "panel glass" },
    el(
      "div",
      { class: "callout danger" },
      el("span", { class: "callout-icon", text: "!" }),
      el(
        "div",
        {},
        el("strong", { text: code.replace(/_/g, " ").toLowerCase() }),
        el("div", { text: (error && error.message) || "The request failed." }),
      ),
    ),
    retry
      ? el(
          "div",
          { class: "row" },
          el("button", { class: "btn btn-sm", type: "button", text: "Try again", onClick: retry }),
        )
      : null,
  );
}

async function render() {
  const parsed = parseHash();
  const def = routeDef(parsed.name);
  const seq = ++state.seq;
  teardown();

  const controller = new AbortController();
  state.controller = controller;
  state.title = def.title;
  state.crumb = def.crumb;
  document.title = `${def.title} — Liquid Glass Crypto Lab`;
  state.onChange?.({ name: def.name, params: parsed.params, query: parsed.query, hidden: Boolean(def.hidden) });

  if (!state.view) return;
  mount(state.view, skeleton());

  const setMeta = (meta) => {
    if (seq !== state.seq) return;
    if (meta.title) {
      state.title = meta.title;
      document.title = `${meta.title} — Liquid Glass Crypto Lab`;
    }
    if (meta.crumb) state.crumb = meta.crumb;
    state.onChange?.({
      name: def.name,
      params: parsed.params,
      query: parsed.query,
      hidden: Boolean(def.hidden),
      title: state.title,
      crumb: state.crumb,
    });
  };

  const ctx = {
    params: parsed.params,
    query: parsed.query,
    signal: controller.signal,
    setMeta,
    reload: () => {
      if (seq === state.seq) render();
    },
    navigate,
    onCleanup: (fn) => {
      if (typeof fn === "function") state.cleanups.push(fn);
    },
    isActive: () => seq === state.seq && !controller.signal.aborted,
  };

  try {
    const mod = await def.load();
    if (seq !== state.seq) return;
    const page = mod.default || mod;
    if (page.title) {
      state.title = page.title;
      document.title = `${page.title} — Liquid Glass Crypto Lab`;
      state.onChange?.({
        name: def.name,
        params: parsed.params,
        query: parsed.query,
        hidden: Boolean(def.hidden),
        title: state.title,
        crumb: page.crumb || state.crumb,
      });
    }
    const result = await page.render(ctx);
    if (seq !== state.seq) return;
    if (result instanceof Node) {
      mount(state.view, result);
      window.scrollTo({ top: 0, behavior: "auto" });
      state.view.focus({ preventScroll: true });
    }
  } catch (error) {
    if (error && error.name === "AbortError") return;
    if (seq !== state.seq) return;
    console.error("route render failed", error);
    mount(state.view, errorPanel(error, () => render()));
  }
}

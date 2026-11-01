/* Watchlist: the tokens the lab is tracking by hand. */

import { api } from "../api.js";
import { num, price } from "../format.js";
import {
  callout,
  dataTable,
  el,
  input,
  modal,
  mount,
  pageHead,
  panel,
  toast,
  toastError,
} from "../ui.js";
import {
  REFRESH_MS,
  ageCell,
  chainCell,
  changeCell,
  listen,
  onGlobalRefresh,
  openBuySheet,
  poll,
  scoreCell,
  securityBadge,
  signalBadge,
  statTiles,
  tokenIdentity,
  usdCell,
} from "./shared.js";

export default {
  title: "Watchlist",
  crumb: "Desk",
  render(ctx) {
    const state = { data: null, rows: [] };
    const statsNode = el("div", {});
    const body = el("div", {});

    const addBtn = el("button", { class: "btn btn-sm btn-primary", type: "button", text: "Add token" });
    const exportBtn = el("button", { class: "btn btn-sm btn-ghost", type: "button", text: "CSV" });

    const root = el(
      "div",
      { class: "stack" },
      pageHead({
        eyebrow: "Manual research list",
        title: "Watchlist",
        description:
          "Tokens pinned for a closer look. A watchlist entry never bypasses strategy, security or risk gates — it only keeps the token in rotation for rechecks.",
        actions: [addBtn, exportBtn],
      }),
      statsNode,
      panel({
        title: "Watched tokens",
        subtitle: "Scores refresh on each scanner tick",
        body,
      }),
    );

    mount(statsNode, el("div", { class: "skeleton", style: { height: "118px" } }));
    mount(body, el("div", { class: "skeleton skeleton-row" }), el("div", { class: "skeleton skeleton-row" }));

    addBtn.addEventListener("click", openAdd);
    exportBtn.addEventListener("click", async () => {
      if (!state.rows.length) {
        toast({ title: "Nothing to export", message: "Add a token first.", type: "warning" });
        return;
      }
      const { csv, downloadCsv } = await import("../format.js");
      downloadCsv(
        "watchlist.csv",
        csv(state.rows, [
          { label: "Symbol", value: (row) => row.symbol },
          { label: "Chain", value: (row) => row.chain },
          { label: "Address", value: (row) => row.address },
          { label: "Price", value: (row) => row.price_usd },
          { label: "Liquidity", value: (row) => row.liquidity_usd },
          { label: "Score", value: (row) => (row.score ? row.score.score : "") },
          { label: "Security", value: (row) => (row.security ? row.security.overall : "NO DATA") },
          { label: "Signal", value: (row) => row.strategy_signal },
        ]),
      );
    });

    function render() {
      const rows = state.rows;
      const scored = rows.filter((row) => row.score);
      const safe = rows.filter((row) => row.security && row.security.overall === "PASS");
      const withPosition = rows.filter((row) => row.has_position);
      mount(
        statsNode,
        statTiles([
          { label: "Watched", value: String(rows.length), foot: "manual research list" },
          { label: "Average score", value: scored.length ? (scored.reduce((sum, row) => sum + num(row.score.score), 0) / scored.length).toFixed(1) : "—", foot: `${scored.length} scored` },
          { label: "Security PASS", value: String(safe.length), foot: `${rows.length - safe.length} warning / unknown / fail` },
          { label: "In a position", value: String(withPosition.length), foot: "already paper-traded" },
        ]),
      );
      mount(
        body,
        dataTable({
          columns: [
            { label: "Token", render: (row) => tokenIdentity(row) },
            { label: "Chain", render: (row) => chainCell(row.chain) },
            { label: "Age", align: "right", render: (row) => ageCell(row.age_minutes) },
            { label: "Price", align: "right", render: (row) => el("span", { class: "numeric", text: price(row.price_usd) }) },
            { label: "1h", align: "right", render: (row) => changeCell(row.pct_h1) },
            { label: "Liquidity", align: "right", render: (row) => usdCell(row.liquidity_usd, 0) },
            { label: "Security", align: "center", render: (row) => securityBadge(row.security) },
            { label: "Score", align: "right", render: (row) => scoreCell(row.score) },
            { label: "Signal", align: "center", render: (row) => signalBadge(row.strategy_signal) },
            {
              label: "",
              align: "right",
              render: (row) =>
                el(
                  "div",
                  { class: "row", style: { gap: "4px", justifyContent: "flex-end" } },
                  el("button", {
                    class: "btn btn-xs btn-primary",
                    type: "button",
                    text: "Paper buy",
                    onClick: (event) => {
                      event.stopPropagation();
                      openBuySheet(row, { onDone: load });
                    },
                  }),
                  el("button", {
                    class: "btn btn-xs btn-danger",
                    type: "button",
                    text: "Remove",
                    onClick: (event) => {
                      event.stopPropagation();
                      remove(row);
                    },
                  }),
                ),
            },
          ],
          rows,
          onRowClick: (row) => (window.location.hash = `#/token/${row.id}`),
          emptyState: el(
            "div",
            { class: "empty" },
            el("div", { class: "empty-icon", text: "★" }),
            el("h4", { text: "Nothing watched yet" }),
            el("p", { class: "muted", text: "Pin tokens from the scanner to keep them in rotation for rechecks." }),
            el("button", { class: "btn btn-sm btn-primary", type: "button", text: "Add a token", onClick: openAdd }),
          ),
        }),
      );
    }

    async function load() {
      try {
        const data = await api.watchlist();
        if (!ctx.isActive()) return;
        state.data = data;
        state.rows = data.tokens || [];
        render();
      } catch (error) {
        if (!ctx.isActive()) return;
        state.rows = [];
        render();
        mount(body, callout({ tone: "danger", title: "Watchlist unavailable", children: error.message }));
      }
    }

    async function remove(row) {
      try {
        await api.removeWatchlist(row.id);
        toast({ title: "Removed", message: row.symbol, type: "info" });
        load();
      } catch (error) {
        toastError(error);
      }
    }

    function openAdd() {
      const search = input({ type: "search", placeholder: "Search symbol, name or address", "aria-label": "Search tokens" });
      const results = el("div", { class: "stack", style: { gap: "6px", maxHeight: "320px", overflowY: "auto" } });
      const hint = el("p", { class: "hint", text: "Showing recently discovered tokens. Search across the 6-hour window." });
      let timer = null;

      async function runSearch() {
        const query = search.value.trim();
        mount(results, el("div", { class: "skeleton skeleton-row" }));
        try {
          const payload = await api.tokens({ search: query || undefined, window_hours: query ? undefined : 6, limit: 8, sort: "score" });
          const rows = payload.tokens || [];
          if (!rows.length) {
            mount(results, el("p", { class: "muted", text: "No tokens matched." }));
            return;
          }
          mount(
            results,
            ...rows.map((row) =>
              el(
                "div",
                { class: "row-between", style: { padding: "8px 10px", border: "1px solid var(--stroke-faint)", borderRadius: "10px" } },
                el("div", { class: "row", style: { gap: "10px", minWidth: 0 } }, tokenIdentity(row), chainCell(row.chain)),
                el(
                  "div",
                  { class: "row", style: { gap: "8px" } },
                  scoreCell(row.score),
                  row.in_watchlist
                    ? el("span", { class: "badge badge-pass", text: "Watched" })
                    : el("button", {
                        class: "btn btn-xs btn-primary",
                        type: "button",
                        text: "Add",
                        onClick: async (event) => {
                          event.currentTarget.disabled = true;
                          try {
                            await api.addWatchlist(row.id);
                            toast({ title: "Added to watchlist", message: row.symbol, type: "success" });
                            sheet.close();
                            load();
                          } catch (error) {
                            toastError(error);
                            event.currentTarget.disabled = false;
                          }
                        },
                      }),
                ),
              ),
            ),
          );
        } catch (error) {
          mount(results, callout({ tone: "danger", title: "Search failed", children: error.message }));
        }
      }

      search.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(runSearch, 320);
      });
      const sheet = modal({
        title: "Add to watchlist",
        subtitle: "Search the discovery feed, then pin a token for rechecks.",
        body: el("div", { class: "stack" }, search, hint, results),
      });
      runSearch();
    }

    poll(ctx, REFRESH_MS, load);
    listen(ctx, ["watchlist", "scanner"], load);
    onGlobalRefresh(ctx, load);
    load();
    return root;
  },
};

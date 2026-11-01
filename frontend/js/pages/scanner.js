/* Live Scanner: discovery feed, filters and manual paper entries. */

import { api } from "../api.js";
import { countdown, csv, downloadCsv, money, num, price, timeAgo } from "../format.js";
import {
  badge,
  callout,
  dataTable,
  el,
  empty,
  input,
  mount,
  pageHead,
  panel,
  scorePill,
  select,
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
  tokenIdentity,
  usdCell,
} from "./shared.js";

export default {
  title: "Live Scanner",
  crumb: "Desk",
  render(ctx) {
    const state = {
      chain: "",
      search: "",
      minScore: "",
      security: "",
      signal: "",
      sort: "score",
      order: "desc",
      watchOnly: false,
      view: "table",
      tokens: [],
      total: 0,
      loading: false,
      status: null,
    };

    const statusBody = el("div", {});
    const resultsBody = el("div", {});
    const resultMeta = el("span", { class: "result-count", text: "Loading…" });
    const runsBody = el("div", {});
    const countdownNode = el("span", { class: "numeric", text: "—" });

    const runBtn = el("button", { class: "btn btn-sm", type: "button", text: "Run scan now" });
    const powerBtn = el("button", { class: "btn btn-sm btn-primary", type: "button", text: "Start scanner" });
    const viewBtn = el("button", { class: "btn btn-sm btn-ghost", type: "button", text: "Card view" });
    const exportBtn = el("button", { class: "btn btn-sm btn-ghost", type: "button", text: "CSV" });

    const filterBar = el("div", { class: "filter-bar", role: "search", "aria-label": "Token filters" });
    const searchInput = input({
      type: "search",
      placeholder: "Search symbol, name or address",
      "aria-label": "Search tokens",
    });
    const chainSelect = select(
      [
        { value: "", label: "All chains" },
        { value: "solana", label: "Solana" },
        { value: "bsc", label: "BNB Chain" },
      ],
      { "aria-label": "Chain filter" },
    );
    const scoreSelect = select(
      [
        { value: "", label: "Any score" },
        { value: "50", label: "Score ≥ 50" },
        { value: "62", label: "Score ≥ 62" },
        { value: "75", label: "Score ≥ 75" },
      ],
      { "aria-label": "Minimum score" },
    );
    const securitySelect = select(
      [
        { value: "", label: "Any security" },
        { value: "PASS", label: "PASS only" },
        { value: "WARNING", label: "WARNING" },
        { value: "FAIL", label: "FAIL" },
        { value: "UNKNOWN", label: "UNKNOWN" },
      ],
      { "aria-label": "Security status" },
    );
    const signalSelect = select(
      [
        { value: "", label: "Any signal" },
        { value: "ENTER", label: "ENTER" },
        { value: "HOLD", label: "HOLD" },
        { value: "REJECT", label: "REJECT" },
        { value: "EXIT", label: "EXIT" },
      ],
      { "aria-label": "Strategy signal" },
    );
    const sortSelect = select(
      [
        { value: "score", label: "Sort: score" },
        { value: "confidence", label: "Sort: confidence" },
        { value: "liquidity", label: "Sort: liquidity" },
        { value: "volume", label: "Sort: 1h volume" },
        { value: "price_change", label: "Sort: 1h change" },
        { value: "age", label: "Sort: age" },
        { value: "symbol", label: "Sort: symbol" },
      ],
      { "aria-label": "Sort field" },
    );
    const orderSelect = select(
      [
        { value: "desc", label: "Descending" },
        { value: "asc", label: "Ascending" },
      ],
      { "aria-label": "Sort direction" },
    );
    const watchChip = el("button", { class: "chip", type: "button", text: "Watchlist only" });

    filterBar.append(
      el("div", { class: "search grow" }, searchInput),
      chainSelect,
      scoreSelect,
      securitySelect,
      signalSelect,
      sortSelect,
      orderSelect,
      watchChip,
      el("span", { class: "result-count", text: "6h window" }),
    );

    const root = el(
      "div",
      { class: "stack" },
      pageHead({
        eyebrow: "Independent 60-second loop",
        title: "Live Scanner",
        description:
          "GeckoTerminal new pools, enriched by DEX Screener, screened by GoPlus and RugCheck, then scored 0–100. Paper entries only fire when every strategy gate passes.",
        actions: [powerBtn, runBtn],
      }),
      panel({
        title: "Scanner control",
        subtitle: "One guarded loop, a database lease and a 45-second minimum gap prevent double scans.",
        actions: el("span", { class: "connection" }, el("span", { class: "dot" }), countdownNode),
        body: statusBody,
      }),
      filterBar,
      panel({
        title: "Discovered tokens",
        subtitle: "Only pools first seen inside the 6-hour discovery window are listed.",
        actions: el("div", { class: "row wrap" }, resultMeta, viewBtn, exportBtn),
        body: resultsBody,
      }),
      panel({
        title: "Recent scanner runs",
        subtitle: "Every tick is recorded, including degraded runs caused by provider rate limits.",
        body: runsBody,
      }),
    );

    searchInput.addEventListener("input", debounce(() => {
      state.search = searchInput.value.trim();
      loadTokens();
    }, 300));
    chainSelect.addEventListener("change", () => {
      state.chain = chainSelect.value;
      loadTokens();
    });
    scoreSelect.addEventListener("change", () => {
      state.minScore = scoreSelect.value;
      loadTokens();
    });
    securitySelect.addEventListener("change", () => {
      state.security = securitySelect.value;
      loadTokens();
    });
    signalSelect.addEventListener("change", () => {
      state.signal = signalSelect.value;
      loadTokens();
    });
    sortSelect.addEventListener("change", () => {
      state.sort = sortSelect.value;
      loadTokens();
    });
    orderSelect.addEventListener("change", () => {
      state.order = orderSelect.value;
      loadTokens();
    });
    watchChip.addEventListener("click", () => {
      state.watchOnly = !state.watchOnly;
      watchChip.classList.toggle("active", state.watchOnly);
      loadTokens();
    });
    viewBtn.addEventListener("click", () => {
      state.view = state.view === "table" ? "cards" : "table";
      viewBtn.textContent = state.view === "table" ? "Card view" : "Table view";
      renderResults();
    });
    exportBtn.addEventListener("click", () => {
      if (!state.tokens.length) {
        toast({ title: "Nothing to export", message: "Run a scan or loosen the filters.", type: "warning" });
        return;
      }
      downloadCsv(
        `scanner-${new Date().toISOString().slice(0, 10)}.csv`,
        csv(state.tokens, [
          { label: "Symbol", value: (row) => row.symbol },
          { label: "Name", value: (row) => row.name },
          { label: "Chain", value: (row) => row.chain },
          { label: "Address", value: (row) => row.address },
          { label: "Age minutes", value: (row) => row.age_minutes ?? "" },
          { label: "Price USD", value: (row) => row.price_usd },
          { label: "Liquidity USD", value: (row) => row.liquidity_usd },
          { label: "Volume 1h", value: (row) => row.volume_h1 },
          { label: "Change 1h %", value: (row) => row.pct_h1 },
          { label: "Score", value: (row) => (row.score ? row.score.score : "") },
          { label: "Confidence", value: (row) => row.data_confidence },
          { label: "Security", value: (row) => (row.security ? row.security.overall : "NO DATA") },
          { label: "Signal", value: (row) => row.strategy_signal },
        ]),
      );
    });

    powerBtn.addEventListener("click", async () => {
      powerBtn.disabled = true;
      try {
        const running = state.status && state.status.state === "running";
        const result = running ? await api.scannerStop() : await api.scannerStart();
        toast({
          title: running ? "Scanner stopped" : "Scanner started",
          message: running
            ? "The background loop is stopped. The external cron can still trigger ticks."
            : "The 60-second loop is running inside the API process.",
          type: "success",
        });
        state.status = result.status || state.status;
        renderStatus();
      } catch (error) {
        toastError(error);
      } finally {
        powerBtn.disabled = false;
      }
    });

    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      runBtn.textContent = "Scanning…";
      try {
        const result = await api.scannerTick();
        toast({
          title: result.status === "SKIPPED" ? "Scan skipped" : `Scan ${String(result.status).toLowerCase()}`,
          message:
            result.skipped_reason ||
            `${result.discovered} discovered · ${result.snapshots} snapshots · ${result.scored} scored · ${result.entries} entries · ${result.duration_ms} ms`,
          type: result.status === "FAILED" ? "error" : "success",
          timeout: 6000,
        });
        await Promise.all([loadStatus(), loadTokens(), loadRuns()]);
      } catch (error) {
        toastError(error);
      } finally {
        runBtn.disabled = false;
        runBtn.textContent = "Run scan now";
      }
    });

    function renderStatus() {
      const scanner = state.status;
      if (!scanner) {
        mount(statusBody, el("div", { class: "skeleton", style: { height: "90px" } }));
        return;
      }
      const run = scanner.last_run || {};
      powerBtn.textContent = scanner.state === "running" ? "Stop scanner" : "Start scanner";
      powerBtn.classList.toggle("btn-primary", scanner.state !== "running");
      const facts = [
        { label: "State", value: scanner.state === "running" ? "Running" : "Stopped" },
        { label: "Enabled", value: scanner.enabled ? "Yes" : "No" },
        { label: "Interval", value: `${scanner.interval_seconds}s` },
        { label: "Last success", value: scanner.last_success_at ? timeAgo(scanner.last_success_at) : "never" },
        { label: "Last tick", value: scanner.last_tick_at ? timeAgo(scanner.last_tick_at) : "never" },
        { label: "Lease owner", value: scanner.lease && scanner.lease.owner ? scanner.lease.owner : "free" },
      ];
      mount(
        statusBody,
        el(
          "div",
          { class: "grid" },
          ...facts.map((fact) =>
            el(
              "div",
              { class: "col-2" },
              el(
                "div",
                { class: "config-item" },
                el("span", { class: "cfg-label" }, el("span", { text: fact.label })),
                el("strong", { class: "numeric", text: String(fact.value) }),
              ),
            ),
          ),
        ),
        scanner.stale
          ? callout({
              tone: "warning",
              title: "Heartbeat is stale",
              children:
                "The scanner has not completed a tick within three intervals. On a free host this usually means the instance slept — the external keep-alive should wake it.",
            })
          : null,
        el(
          "div",
          { class: "row wrap", style: { gap: "8px" } },
          el("span", { class: "badge badge-info", text: `last run ${run.status || "—"}` }),
          el("span", { class: "badge badge-info", text: `${run.discovered ?? 0} discovered` }),
          el("span", { class: "badge badge-info", text: `${run.enriched ?? 0} enriched` }),
          el("span", { class: "badge badge-info", text: `${run.snapshots ?? 0} snapshots` }),
          el("span", { class: "badge badge-info", text: `${run.scored ?? 0} scored` }),
          run.entries ? el("span", { class: "badge badge-pass", text: `${run.entries} entries` }) : null,
          run.exits ? el("span", { class: "badge badge-warning", text: `${run.exits} exits` }) : null,
          el("span", { class: `badge ${scanner.consecutive_failures ? "badge-warning" : "badge-pass"}`, text: `${scanner.consecutive_failures} failures` }),
          el("span", { class: "badge badge-unknown", text: `${scanner.errors_last_hour ?? 0} errors / 1h` }),
        ),
        providerRow(scanner.providers),
      );
      updateCountdown();
    }

    function updateCountdown() {
      const scanner = state.status;
      countdownNode.textContent = scanner && scanner.next_scan_at ? `Next scan ${countdown(scanner.next_scan_at)}` : "Next scan —";
    }

    function providerRow(providers) {
      const names = ["geckoterminal", "dexscreener", "goplus", "rugcheck"];
      return el(
        "div",
        { class: "row wrap", style: { gap: "8px" } },
        ...names.map((name) => {
          const info = (providers || {})[name] || {};
          const ok = !info.circuit_open && (info.consecutive_failures || 0) === 0;
          return el(
            "span",
            {
              class: `badge ${ok ? "badge-pass" : "badge-warning"}`,
              title: `${info.requests ?? 0} requests · last error: ${info.last_error || "none"}`,
            },
            el("span", { class: "dot" }),
            name,
          );
        }),
        el("span", { class: "badge badge-unknown", text: `${scanner_subscribers(state.status)} live subscribers` }),
      );
    }

    function scanner_subscribers(scanner) {
      return scanner ? scanner.subscribers ?? 0 : 0;
    }

    function renderResults() {
      resultMeta.textContent = state.loading
        ? "Loading…"
        : `${state.total} token${state.total === 1 ? "" : "s"} · updated ${timeAgo(new Date().toISOString())}`;
      if (state.loading && !state.tokens.length) {
        mount(resultsBody, el("div", { class: "skeleton skeleton-row" }), el("div", { class: "skeleton skeleton-row" }));
        return;
      }
      if (!state.tokens.length) {
        mount(
          resultsBody,
          empty({
            icon: "◇",
            title: "No matching tokens",
            message: "Loosen the filters, or run a scan to collect fresh pools from both chains.",
          }),
        );
        return;
      }
      if (state.view === "cards") {
        mount(resultsBody, el("div", { class: "token-grid" }, ...state.tokens.map((row) => tokenCard(row))));
        return;
      }
      mount(
        resultsBody,
        dataTable({
          columns: [
            { label: "Token", render: (row) => tokenIdentity(row) },
            { label: "Chain", render: (row) => chainCell(row.chain) },
            { label: "Age", align: "right", render: (row) => ageCell(row.age_minutes) },
            { label: "Price", align: "right", render: (row) => el("span", { class: "numeric", text: price(row.price_usd) }) },
            { label: "Liquidity", align: "right", render: (row) => usdCell(row.liquidity_usd, 0) },
            { label: "1h volume", align: "right", render: (row) => usdCell(row.volume_h1, 0) },
            { label: "1h", align: "right", render: (row) => changeCell(row.pct_h1) },
            { label: "Buys / sells", align: "right", render: (row) => el("span", { class: "numeric", text: `${row.buys_h1 ?? 0} / ${row.sells_h1 ?? 0}` }) },
            { label: "Security", align: "center", render: (row) => securityBadge(row.security) },
            { label: "Score", align: "right", render: (row) => scoreCell(row.score) },
            { label: "Signal", align: "center", render: (row) => signalBadge(row.strategy_signal) },
            { label: "", align: "right", render: (row) => rowActions(row) },
          ],
          rows: state.tokens,
          onRowClick: (row) => (window.location.hash = `#/token/${row.id}`),
        }),
      );
    }

    function rowActions(row) {
      return el(
        "div",
        { class: "row", style: { gap: "4px", justifyContent: "flex-end" } },
        el("button", {
          class: `btn btn-xs ${row.in_watchlist ? "btn-success" : "btn-ghost"}`,
          type: "button",
          text: row.in_watchlist ? "★" : "☆",
          title: row.in_watchlist ? "Remove from watchlist" : "Add to watchlist",
          "aria-label": row.in_watchlist ? "Remove from watchlist" : "Add to watchlist",
          onClick: (event) => {
            event.stopPropagation();
            toggleWatch(row);
          },
        }),
        el("button", {
          class: "btn btn-xs btn-primary",
          type: "button",
          text: "Paper buy",
          onClick: (event) => {
            event.stopPropagation();
            openBuy(row);
          },
        }),
      );
    }

    function tokenCard(row) {
      return el(
        "article",
        { class: "token-card" },
        el("div", { class: "tc-head" }, tokenIdentity(row), chainCell(row.chain)),
        el(
          "div",
          { class: "tc-metrics" },
          metric("Price", price(row.price_usd)),
          metric("1h", `${num(row.pct_h1) > 0 ? "+" : ""}${num(row.pct_h1).toFixed(1)}%`, num(row.pct_h1)),
          metric("Liquidity", money(row.liquidity_usd, 0)),
        ),
        el(
          "div",
          { class: "tc-foot" },
          el(
            "div",
            { class: "tc-score" },
            scorePill(row.score ? row.score.score : 0, row.data_confidence),
            el("span", { class: "muted", text: `${ageCell(row.age_minutes).textContent} old` }),
          ),
          el(
            "div",
            { class: "row", style: { gap: "4px" } },
            securityBadge(row.security),
            signalBadge(row.strategy_signal),
          ),
        ),
        el(
          "div",
          { class: "row", style: { gap: "6px" } },
          el("a", { class: "btn btn-xs btn-ghost", href: `#/token/${row.id}`, text: "Details" }),
          el("button", {
            class: `btn btn-xs ${row.in_watchlist ? "btn-success" : "btn-ghost"}`,
            type: "button",
            text: row.in_watchlist ? "Watching" : "Watch",
            onClick: () => toggleWatch(row),
          }),
          el("button", { class: "btn btn-xs btn-primary", type: "button", text: "Paper buy", onClick: () => openBuy(row) }),
        ),
      );
    }

    function metric(label, value, tone) {
      return el(
        "div",
        { class: "tc-metric" },
        el("span", { text: label }),
        el("strong", { class: tone == null ? "" : num(tone) >= 0 ? "pos" : "neg", text: value }),
      );
    }

    async function toggleWatch(row) {
      try {
        if (row.in_watchlist) {
          await api.unwatchToken(row.id);
          row.in_watchlist = false;
          toast({ title: "Removed from watchlist", message: row.symbol, type: "info" });
        } else {
          await api.watchToken(row.id);
          row.in_watchlist = true;
          toast({ title: "Added to watchlist", message: row.symbol, type: "success" });
        }
        renderResults();
      } catch (error) {
        toastError(error);
      }
    }

    function openBuy(row) {
      openBuySheet(row, {
        onDone: () => {
          loadTokens();
          loadStatus();
        },
      });
    }


    function renderRuns() {
      if (!state.runs) {
        mount(runsBody, el("div", { class: "skeleton skeleton-row" }));
        return;
      }
      const rows = state.runs.runs || [];
      mount(
        runsBody,
        dataTable({
          columns: [
            { label: "Started", render: (row) => el("span", { class: "numeric", text: row.started_at ? timeAgo(row.started_at) : "—" }) },
            { label: "Status", render: (row) => badge(row.status, row.status) },
            { label: "Source", render: (row) => el("span", { class: "muted", text: row.source }) },
            { label: "Duration", align: "right", render: (row) => el("span", { class: "numeric", text: `${row.duration_ms ?? 0} ms` }) },
            { label: "Discovered", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.discovered ?? 0) }) },
            { label: "Snapshots", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.snapshots ?? 0) }) },
            { label: "Scored", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.scored ?? 0) }) },
            { label: "Entries", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.entries ?? 0) }) },
            { label: "Exits", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.exits ?? 0) }) },
            { label: "Errors", align: "right", render: (row) => el("span", { class: `numeric ${row.errors ? "neg" : ""}`, text: String(row.errors ?? 0) }) },
          ],
          rows,
          emptyState: empty({ title: "No runs recorded yet", message: "The first tick will appear here." }),
        }),
      );
    }

    async function loadStatus() {
      try {
        state.status = await api.scannerStatus();
        if (ctx.isActive()) renderStatus();
      } catch (error) {
        mount(statusBody, callout({ tone: "danger", title: "Scanner status unavailable", children: error.message }));
      }
    }

    async function loadTokens() {
      state.loading = true;
      renderResults();
      try {
        const payload = await api.tokens({
          chain: state.chain || undefined,
          search: state.search || undefined,
          min_score: state.minScore || undefined,
          security: state.security || undefined,
          signal: state.signal || undefined,
          watchlist_only: state.watchOnly ? true : undefined,
          window_hours: 6,
          sort: state.sort,
          order: state.order,
          limit: 120,
        });
        state.tokens = payload.tokens || [];
        state.total = payload.total ?? state.tokens.length;
      } catch (error) {
        state.tokens = [];
        state.total = 0;
        toastError(error);
      } finally {
        state.loading = false;
        if (ctx.isActive()) renderResults();
      }
    }

    async function loadRuns() {
      try {
        state.runs = await api.scannerRuns(12);
        if (ctx.isActive()) renderRuns();
      } catch {
        state.runs = { runs: [] };
        renderRuns();
      }
    }

    const countdownTimer = setInterval(updateCountdown, 1000);
    ctx.onCleanup(() => clearInterval(countdownTimer));
    poll(ctx, REFRESH_MS, loadTokens);
    listen(ctx, ["scanner"], () => {
      loadStatus();
      loadTokens();
    });
    onGlobalRefresh(ctx, () => {
      loadStatus();
      loadTokens();
      loadRuns();
    });

    loadStatus();
    loadTokens();
    loadRuns();
    return root;
  },
};

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

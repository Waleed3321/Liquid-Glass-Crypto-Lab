/* Overview: the desk at a glance. */

import { api } from "../api.js";
import { areaChart } from "../charts.js";
import { clock, countdown, money, num, pct, price, timeAgo } from "../format.js";
import {
  callout,
  dataTable,
  el,
  empty,
  mount,
  panel,
  progressRing,
} from "../ui.js";
import {
  REFRESH_MS,
  chainCell,
  changeCell,
  limitMeters,
  listen,
  onGlobalRefresh,
  poll,
  scoreCell,
  securityBadge,
  signalBadge,
  statTiles,
  tokenIdentity,
  usdCell,
} from "./shared.js";

export default {
  title: "Overview",
  crumb: "Desk",
  render(ctx) {
    const hero = el("section", { class: "panel glass hero" });
    const statsNode = el("div", {});
    const equityBody = el("div", { class: "chart tall", "aria-label": "Equity curve" });
    const riskBody = el("div", {});
    const tableBody = el("div", {});
    const feedBody = el("div", { class: "feed" });
    const scannerBody = el("div", {});
    const accountFoot = el("div", { class: "panel-footer" });

    const equityPanel = panel({
      title: "Equity curve",
      subtitle: "Paper account value from closed trades, starting at $10.00",
      actions: el("span", { class: "label", text: "30 days" }),
      body: equityBody,
      footer: accountFoot,
    });
    const riskPanel = panel({
      title: "Risk guardrails",
      subtitle: "Hard caps enforced inside the trade transaction",
      body: riskBody,
    });
    const tablePanel = panel({
      title: "Top opportunities",
      subtitle: "Highest scoring tokens discovered in the last 6 hours",
      actions: el("a", { class: "btn btn-sm btn-ghost", href: "#/scanner", text: "Open scanner" }),
      body: tableBody,
    });
    const feedPanel = panel({
      title: "Paper activity",
      subtitle: "Latest simulated orders",
      actions: el("a", { class: "btn btn-sm btn-ghost", href: "#/history", text: "History" }),
      body: feedBody,
    });
    const scannerPanel = panel({
      title: "Scanner heartbeat",
      subtitle: "Independent 60-second discovery across Solana and BNB Chain",
      actions: el("a", { class: "btn btn-sm btn-ghost", href: "#/scanner", text: "Scanner desk" }),
      body: scannerBody,
    });

    const root = el(
      "div",
      { class: "stack" },
      hero,
      statsNode,
      el("div", { class: "grid" }, el("div", { class: "col-8" }, equityPanel), el("div", { class: "col-4" }, riskPanel)),
      el("div", { class: "grid" }, el("div", { class: "col-7" }, tablePanel), el("div", { class: "col-5" }, feedPanel)),
      scannerPanel,
    );

    renderHero(null);
    mount(statsNode, statTiles(placeholderTiles()));
    mount(equityBody, el("div", { class: "skeleton", style: { height: "280px" } }));
    mount(riskBody, el("div", { class: "skeleton", style: { height: "180px" } }));
    mount(tableBody, el("div", { class: "skeleton skeleton-row" }), el("div", { class: "skeleton skeleton-row" }));
    mount(feedBody, el("div", { class: "skeleton skeleton-row" }), el("div", { class: "skeleton skeleton-row" }));
    mount(scannerBody, el("div", { class: "skeleton", style: { height: "80px" } }));

    function renderHero(market, portfolio) {
      const heroMeta = market
        ? [
            { value: market.tokens_tracked, label: "Tracked · 6h" },
            { value: market.discovered_last_hour, label: "New · 1h" },
            { value: num(market.avg_score).toFixed(1), label: "Avg score" },
          ]
        : [
            { value: "—", label: "Tracked · 6h" },
            { value: "—", label: "New · 1h" },
            { value: "—", label: "Avg score" },
          ];
      mount(
        hero,
        el(
          "div",
          { class: "hero-copy" },
          el("span", { class: "hero-eyebrow" }, el("span", { class: "dot" }), "Paper-only research desk"),
          el("h2", {}, "New coins, screened in ", el("span", { class: "grad", text: "60 seconds" }), "."),
          el(
            "p",
            {},
            "A conservative momentum-pullback strategy watches Solana and BNB Chain launches for six hours, " +
              "checks contract safety with keyless providers, and only paper-trades when every risk gate passes. " +
              "No wallets, no keys, no real orders.",
          ),
          el(
            "div",
            { class: "hero-meta" },
            ...heroMeta.map((item) =>
              el("div", { class: "hero-metric" }, el("strong", { text: String(item.value ?? "—") }), el("span", { text: item.label })),
            ),
          ),
        ),
        el(
          "div",
          { class: "hero-visual" },
          portfolio
            ? progressRing(
                Math.max(0, Math.min(100, (num(portfolio.equity) / (num(portfolio.initial_balance, 10) || 10)) * 100)),
                "of start",
                `${money(portfolio.equity)} vs ${money(portfolio.initial_balance)}`,
              )
            : progressRing(0, "of $10", "Loading equity…"),
        ),
      );
    }

    async function load() {
      const results = await Promise.allSettled([
        api.portfolio(),
        api.marketAnalytics(),
        api.scannerStatus(),
        api.tradeHistory({ limit: 10 }),
        api.equity(30),
      ]);
      if (!ctx.isActive()) return;
      const [portfolioRes, marketRes, scannerRes, ordersRes, equityRes] = results;

      const portfolio = portfolioRes.status === "fulfilled" ? portfolioRes.value : null;
      const market = marketRes.status === "fulfilled" ? marketRes.value : null;
      const scanner = scannerRes.status === "fulfilled" ? scannerRes.value : null;
      const orders = ordersRes.status === "fulfilled" ? ordersRes.value : null;
      const equity = equityRes.status === "fulfilled" ? equityRes.value : null;

      if (portfolio) {
        const initial = num(portfolio.initial_balance, 10);
        mount(statsNode, statTiles(tilesFromPortfolio(portfolio, market)));
        renderHero(market, portfolio);
        mount(riskBody, limitMeters(portfolio));
        if (portfolio.halted) {
          riskBody.append(
            callout({
              tone: "danger",
              title: "Trading halted",
              children: "The daily loss cap was reached. New entries resume on the next trading day.",
            }),
          );
        }
        mount(
          accountFoot,
          el("span", { text: `Initial ${money(initial)} · Cash ${money(portfolio.cash_balance)}` }),
          el("span", {
            class: `numeric ${num(portfolio.total_pnl) >= 0 ? "pos" : "neg"}`,
            text: `${num(portfolio.total_pnl) >= 0 ? "+" : ""}${money(portfolio.total_pnl)} (${num(
              portfolio.total_pnl_pct,
            ).toFixed(2)}%)`,
          }),
        );
      } else {
        mount(
          riskBody,
          callout({
            tone: "danger",
            title: "Portfolio unavailable",
            children: (portfolioRes.reason && portfolioRes.reason.message) || "The paper account could not be loaded.",
          }),
        );
        mount(statsNode, statTiles(placeholderTiles()));
        mount(accountFoot, el("span", { class: "muted", text: "Portfolio unavailable" }));
        renderHero(market);
      }

      if (equity && equity.points && equity.points.length) {
        areaChart(equityBody, equity.points, { x: "day", y: "equity" });
      } else {
        mount(
          equityBody,
          empty({
            icon: "◌",
            title: "No closed trades yet",
            message: "The equity curve appears after the first paper position is closed.",
          }),
        );
      }

      if (market) {
        const rows = market.top_opportunities || [];
        mount(
          tableBody,
          dataTable({
            columns: [
              { label: "Token", render: (row) => tokenIdentity(row) },
              { label: "Chain", render: (row) => chainCell(row.chain) },
              { label: "Score", align: "right", render: (row) => scoreCell({ score: row.score, confidence: row.confidence }) },
              { label: "Security", align: "center", render: (row) => securityBadge({ overall: row.security }) },
              { label: "Liquidity", align: "right", render: (row) => usdCell(row.liquidity_usd, 0) },
              { label: "1h", align: "right", render: (row) => changeCell(row.pct_h1) },
              { label: "Signal", align: "center", render: (row) => signalBadge(row.signal) },
            ],
            rows,
            emptyState: empty({ icon: "◇", title: "No scored tokens yet", message: "The scanner is collecting its first snapshots." }),
            onRowClick: (row) => (window.location.hash = `#/token/${row.id}`),
          }),
        );
      } else {
        mount(tableBody, callout({ tone: "warning", title: "Market analytics unavailable", children: (marketRes.reason && marketRes.reason.message) || "Retry in a moment." }));
      }

      if (orders && orders.orders && orders.orders.length) {
        mount(feedBody, ...orders.orders.slice(0, 8).map((order) => feedItem(order)));
      } else {
        mount(
          feedBody,
          empty({
            icon: "◇",
            title: "No paper trades yet",
            message: "Entries appear here once the strategy finds a token that clears every gate.",
          }),
        );
      }

      if (scanner) {
        mount(scannerBody, scannerStrip(scanner));
      } else {
        mount(scannerBody, callout({ tone: "warning", title: "Scanner status unavailable", children: (scannerRes.reason && scannerRes.reason.message) || "Retry in a moment." }));
      }
    }

    function feedItem(order) {
      const buy = String(order.side).toUpperCase() === "BUY";
      return el(
        "div",
        { class: "feed-item" },
        el("span", { class: `feed-icon ${buy ? "buy" : "sell"}`, text: buy ? "B" : "S" }),
        el(
          "div",
          { class: "feed-body" },
          el(
            "strong",
            {},
            `${buy ? "Paper buy" : "Paper sell"} · ${order.symbol || `#${order.token_id || ""}`}`,
          ),
          el(
            "span",
            {},
            order.fill_notional != null
              ? `${money(order.fill_notional)} at ${price(order.fill_price)} · ${order.status.toLowerCase()}`
              : order.reason || order.status,
          ),
        ),
        el("span", { class: "feed-time", text: timeAgo(order.created_at || order.filled_at) }),
      );
    }

    function scannerStrip(scanner) {
      const run = scanner.last_run || {};
      const next = scanner.next_scan_at ? countdown(scanner.next_scan_at) : "—";
      const providers = scanner.providers || {};
      const providerNames = ["geckoterminal", "dexscreener", "goplus", "rugcheck"];
      return el(
        "div",
        { class: "stack", style: { gap: "16px" } },
        el(
          "div",
          { class: "grid" },
          ...[
            { label: "State", value: scanner.state === "running" ? "Running" : "Stopped" },
            { label: "Next scan", value: next },
            { label: "Last success", value: scanner.last_success_at ? clock(scanner.last_success_at) : "never" },
            { label: "Discovered", value: `${run.discovered ?? 0} pools` },
            { label: "Snapshots", value: String(run.snapshots ?? 0) },
            { label: "Scored", value: String(run.scored ?? 0) },
          ].map((cell) =>
            el(
              "div",
              { class: "col-2" },
              el(
                "div",
                { class: "config-item" },
                el("span", { class: "cfg-label" }, el("span", { text: cell.label })),
                el("strong", { class: "numeric", text: cell.value }),
              ),
            ),
          ),
        ),
        el(
          "div",
          { class: "row wrap", style: { gap: "8px" } },
          ...providerNames.map((name) => {
            const info = providers[name];
            const ok = info && !info.circuit_open;
            return el(
              "span",
              {
                class: `badge ${ok ? "badge-pass" : "badge-warning"}`,
                title: info ? `${info.requests ?? 0} requests · ${info.last_error || "healthy"}` : "Not configured",
              },
              el("span", { class: "dot" }),
              name,
            );
          }),
          scanner.stale
            ? el("span", { class: "badge badge-warning", text: "heartbeat stale" })
            : el("span", { class: "badge badge-pass", text: "heartbeat fresh" }),
          scanner.errors_last_hour ? el("span", { class: "badge badge-warning", text: `${scanner.errors_last_hour} errors · 1h` }) : null,
        ),
      );
    }

    const throttled = throttle(load, 1200);
    poll(ctx, REFRESH_MS, load);
    listen(ctx, ["scanner", "trade"], throttled);
    onGlobalRefresh(ctx, load);

    load();
    return root;
  },
};

function tilesFromPortfolio(portfolio, market) {
  const daily = num(portfolio.daily_pnl);
  const chainText = market
    ? Object.entries(market.by_chain || {})
        .map(([chain, count]) => `${chain === "bsc" ? "BNB" : "SOL"} ${count}`)
        .join(" · ")
    : "—";
  return [
    {
      label: "Equity",
      value: money(portfolio.equity),
      foot: el(
        "span",
        {},
        `${money(portfolio.cash_balance)} cash · ${money(portfolio.market_value)} positions`,
      ),
      spark: null,
    },
    {
      label: "Today's P&L",
      value: el("span", { class: daily >= 0 ? "pos" : "neg", text: `${daily >= 0 ? "+" : ""}${money(daily)}` }),
      foot: `Realized ${money(portfolio.daily_realized_pnl)} · Unrealized ${money(portfolio.unrealized_pnl)}`,
    },
    {
      label: "Open positions",
      value: `${portfolio.open_positions} / ${portfolio.max_open_positions}`,
      foot: `Win rate ${pct(portfolio.win_rate, 1)} · ${portfolio.closed_positions} closed`,
    },
    {
      label: "Discovered · 6h",
      value: market ? String(market.tokens_tracked) : "—",
      foot: chainText || "—",
    },
  ];
}

function placeholderTiles() {
  return [
    { label: "Equity", value: "—", foot: "Loading…" },
    { label: "Today's P&L", value: "—", foot: "Loading…" },
    { label: "Open positions", value: "— / 3", foot: "Loading…" },
    { label: "Discovered · 6h", value: "—", foot: "Loading…" },
  ];
}

function throttle(fn, wait) {
  let last = 0;
  let timer = null;
  return (...args) => {
    const now = Date.now();
    const remaining = wait - (now - last);
    if (remaining <= 0) {
      last = now;
      fn(...args);
      return;
    }
    clearTimeout(timer);
    timer = setTimeout(() => {
      last = Date.now();
      fn(...args);
    }, remaining);
  };
}

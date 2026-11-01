/* Paper Portfolio: valuation, performance and allocation. */

import { api } from "../api.js";
import { areaChart, donutChart, renderEmpty } from "../charts.js";
import { money, num, pct, price, timeAgo } from "../format.js";
import { callout, dataTable, el, empty, mount, pageHead, panel } from "../ui.js";
import {
  REFRESH_MS,
  chainCell,
  limitMeters,
  listen,
  onGlobalRefresh,
  openSellSheet,
  poll,
  sideBadge,
  statTiles,
  timeCell,
  usdCell,
} from "./shared.js";

export default {
  title: "Paper Portfolio",
  crumb: "Paper book",
  render(ctx) {
    const state = { portfolio: null, performance: null, history: null };
    const statsNode = el("div", {});
    const secondaryNode = el("div", {});
    const chartBody = el("div", { class: "chart tall" });
    const riskBody = el("div", {});
    const allocationBody = el("div", { class: "chart", style: { minHeight: "260px" } });
    const perfBody = el("div", {});
    const positionsBody = el("div", {});
    const dailyBody = el("div", {});
    const ordersBody = el("div", {});
    const footNode = el("div", { class: "panel-footer" });

    const root = el(
      "div",
      { class: "stack" },
      pageHead({
        eyebrow: "Simulated book · $10.00 start",
        title: "Paper Portfolio",
        description:
          "Every fill is simulated from public snapshots with impact, slippage, network fees, DEX fees and known token tax. Hard caps are enforced server-side inside a single risk transaction.",
        actions: [el("a", { class: "btn btn-sm", href: "#/positions", text: "Open positions" }), el("a", { class: "btn btn-sm btn-ghost", href: "#/history", text: "Trade history" })],
      }),
      statsNode,
      secondaryNode,
      el("div", { class: "grid" }, el("div", { class: "col-8" }, panel({ title: "Equity curve", subtitle: "Starting balance plus cumulative realized P&L", body: chartBody, footer: footNode })), el("div", { class: "col-4" }, panel({ title: "Risk guardrails", subtitle: "Live caps for this paper account", body: riskBody }))),
      el("div", { class: "grid" }, el("div", { class: "col-5" }, panel({ title: "Allocation", subtitle: "Cash plus open position market value", body: allocationBody })), el("div", { class: "col-7" }, panel({ title: "Performance", subtitle: "Closed-trade statistics", body: perfBody }))),
      panel({ title: "Open positions", subtitle: "Marked at the latest scanner snapshot", body: positionsBody }),
      panel({ title: "Daily performance", subtitle: "One persisted row per trading day — restarts cannot reset the loss budget", body: dailyBody }),
      panel({ title: "Recent orders", subtitle: "Newest simulated orders", actions: el("a", { class: "btn btn-sm btn-ghost", href: "#/history", text: "All orders" }), body: ordersBody }),
    );

    for (const node of [statsNode, secondaryNode, riskBody, perfBody, positionsBody, dailyBody, ordersBody]) {
      mount(node, el("div", { class: "skeleton skeleton-row" }), el("div", { class: "skeleton skeleton-row" }));
    }
    mount(chartBody, el("div", { class: "skeleton", style: { height: "300px" } }));
    mount(allocationBody, el("div", { class: "skeleton", style: { height: "240px" } }));

    async function load() {
      const results = await Promise.allSettled([api.portfolio(), api.performance(), api.equity(30), api.tradeHistory({ limit: 12 })]);
      if (!ctx.isActive()) return;
      const [portfolioRes, performanceRes, equityRes, historyRes] = results;
      if (portfolioRes.status !== "fulfilled") {
        mount(statsNode, callout({ tone: "danger", title: "Portfolio unavailable", children: portfolioRes.reason.message }));
        return;
      }
      state.portfolio = portfolioRes.value;
      state.performance = performanceRes.status === "fulfilled" ? performanceRes.value : null;
      state.history = historyRes.status === "fulfilled" ? historyRes.value : null;
      const portfolio = state.portfolio;
      const performance = state.performance;
      const equity = equityRes.status === "fulfilled" ? equityRes.value : null;

      mount(statsNode, statTiles(primaryTiles(portfolio)));
      mount(secondaryNode, statTiles(secondaryTiles(portfolio, performance)));
      mount(riskBody, limitMeters(portfolio));
      if (portfolio.halted) {
        riskBody.append(callout({ tone: "danger", title: "Trading halted", children: "The daily loss limit was reached. Entries resume on the next trading day." }));
      }
      mount(
        footNode,
        el("span", { text: `Initial ${money(portfolio.initial_balance)} · ${portfolio.closed_positions} closed positions` }),
        el("span", {
          class: num(portfolio.total_pnl) >= 0 ? "pos numeric" : "neg numeric",
          text: `${num(portfolio.total_pnl) >= 0 ? "+" : ""}${money(portfolio.total_pnl)} (${num(portfolio.total_pnl_pct).toFixed(2)}%)`,
        }),
      );

      if (equity && equity.points && equity.points.length > 1) {
        areaChart(chartBody, equity.points, { x: "day", y: "equity" });
      } else {
        renderEmpty(chartBody, "The equity curve appears after the first closed trade.");
      }

      const allocation = (portfolio.positions || []).map((position, index) => ({
        label: position.symbol || `Position ${position.id}`,
        value: num(position.market_value),
        color: ["#6fa8ff", "#a78bfa", "#31e0a0", "#ffc65c"][index % 4],
      }));
      if (num(portfolio.cash_balance) > 0) allocation.push({ label: "Cash", value: num(portfolio.cash_balance), color: "#33415f" });
      donutChart(allocationBody, allocation, { centerLabel: "EQUITY", centerValue: money(portfolio.equity) });

      if (performance) {
        const entries = [
          ["Trades closed", String(performance.trades)],
          ["Win rate", pct(performance.win_rate, 1)],
          ["Average win", money(performance.avg_win, 4)],
          ["Average loss", money(performance.avg_loss, 4)],
          ["Profit factor", performance.profit_factor == null ? "—" : String(performance.profit_factor)],
          ["Best trade", money(performance.best_trade)],
          ["Worst trade", money(performance.worst_trade)],
        ];
        mount(
          perfBody,
          el(
            "div",
            { class: "grid" },
            ...entries.map(([label, value]) =>
              el(
                "div",
                { class: "col-6" },
                el(
                  "div",
                  { class: "config-item" },
                  el("span", { class: "cfg-label", text: label }),
                  el("strong", { class: "numeric", text: value }),
                ),
              ),
            ),
          ),
          el(
            "div",
            { class: "row wrap", style: { marginTop: "12px", gap: "6px" } },
            el("span", { class: "badge badge-pass", text: `${portfolio.wins} winners` }),
            el("span", { class: "badge badge-fail", text: `${portfolio.losses} losers` }),
            el("span", { class: "badge badge-info", text: `${portfolio.closed_positions} closed` }),
          ),
        );
      } else {
        mount(perfBody, callout({ tone: "warning", title: "Performance unavailable", children: "Retry in a moment." }));
      }

      const positions = portfolio.positions || [];
      mount(
        positionsBody,
        dataTable({
          columns: [
            { label: "Token", render: (row) => el("a", { class: "token-link", href: `#/token/${row.token_id}` }, el("span", { class: "sym" }, el("strong", { text: row.symbol }), el("span", { text: row.name }))) },
            { label: "Chain", render: (row) => chainCell(row.chain) },
            { label: "Entry", align: "right", render: (row) => el("span", { class: "numeric", text: price(row.entry_price) }) },
            { label: "Market", align: "right", render: (row) => el("span", { class: "numeric", text: price(row.market_price) }) },
            { label: "Value", align: "right", render: (row) => usdCell(row.market_value, 4) },
            { label: "Unrealized", align: "right", render: (row) => el("span", { class: `numeric ${num(row.unrealized_pnl) >= 0 ? "pos" : "neg"}`, text: `${num(row.unrealized_pnl) >= 0 ? "+" : ""}${money(row.unrealized_pnl)}` }) },
            { label: "Remaining", align: "right", render: (row) => el("span", { class: "numeric", text: num(row.remaining_qty).toLocaleString(undefined, { maximumFractionDigits: 6 }) }) },
            { label: "", align: "right", render: (row) => el("button", { class: "btn btn-xs btn-danger", type: "button", text: "Sell", onClick: (event) => { event.stopPropagation(); openSellSheet(row, { onDone: load }); } }) },
          ],
          rows: positions,
          onRowClick: (row) => (window.location.hash = `#/token/${row.token_id}`),
          emptyState: empty({ icon: "◇", title: "No open positions", message: "The strategy opens at most three paper positions at a time." }),
        }),
      );

      if (performance && performance.daily && performance.daily.length) {
        mount(
          dailyBody,
          dataTable({
            columns: [
              { label: "Day", render: (row) => el("span", { class: "numeric", text: row.day }) },
              { label: "Trades", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.trades) }) },
              { label: "Entries", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.entries) }) },
              { label: "Exits", align: "right", render: (row) => el("span", { class: "numeric", text: String(row.exits) }) },
              { label: "Realized", align: "right", render: (row) => el("span", { class: `numeric ${num(row.realized_pnl) >= 0 ? "pos" : "neg"}`, text: `${num(row.realized_pnl) >= 0 ? "+" : ""}${money(row.realized_pnl)}` }) },
              { label: "Fees", align: "right", render: (row) => usdCell(row.fees_paid, 4) },
              { label: "Halted", align: "center", render: (row) => (row.halted ? el("span", { class: "badge badge-fail", text: "halted" }) : el("span", { class: "badge badge-pass", text: "clear" })) },
            ],
            rows: [...performance.daily].reverse(),
            emptyState: empty({ title: "No trading days recorded", message: "Daily rows are created when the first trade of a day fills." }),
          }),
        );
      } else {
        mount(dailyBody, empty({ icon: "◌", title: "No trading days yet", message: "Daily rows appear once a paper order fills." }));
      }

      if (state.history && state.history.orders && state.history.orders.length) {
        mount(
          ordersBody,
          dataTable({
            columns: [
              { label: "When", render: (row) => timeCell(row.created_at) },
              { label: "Side", align: "center", render: (row) => sideBadge(row.side) },
              { label: "Token", render: (row) => el("span", { class: "sym" }, el("strong", { text: row.symbol || "—" }), el("span", { text: row.source })) },
              { label: "Notional", align: "right", render: (row) => usdCell(row.fill_notional ?? row.requested_notional, 4) },
              { label: "Price", align: "right", render: (row) => (row.fill_price == null ? el("span", { class: "muted", text: "—" }) : el("span", { class: "numeric", text: price(row.fill_price) })) },
              { label: "Status", align: "center", render: (row) => el("span", { class: `badge ${row.status === "FILLED" ? "badge-pass" : row.status === "REJECTED" ? "badge-fail" : "badge-pending"}`, text: row.status }) },
              { label: "Age", align: "right", render: (row) => el("span", { class: "muted", text: timeAgo(row.created_at) }) },
            ],
            rows: state.history.orders,
            emptyState: empty({ title: "No orders yet", message: "Manual buys and strategy entries appear here." }),
          }),
        );
      } else {
        mount(ordersBody, empty({ icon: "◇", title: "No orders yet", message: "Manual buys and strategy entries appear here." }));
      }
    }

    poll(ctx, REFRESH_MS, load);
    listen(ctx, ["trade", "scanner"], load);
    onGlobalRefresh(ctx, load);
    load();
    return root;
  },
};

function primaryTiles(portfolio) {
  const total = num(portfolio.total_pnl);
  return [
    { label: "Equity", value: money(portfolio.equity), foot: `Initial ${money(portfolio.initial_balance)}` },
    { label: "Total P&L", value: el("span", { class: total >= 0 ? "pos" : "neg", text: `${total >= 0 ? "+" : ""}${money(total)}` }), foot: `${num(portfolio.total_pnl_pct) >= 0 ? "+" : ""}${num(portfolio.total_pnl_pct).toFixed(2)}% vs start` },
    { label: "Cash", value: money(portfolio.cash_balance), foot: `${portfolio.open_positions}/${portfolio.max_open_positions} slots used` },
    { label: "Invested", value: money(portfolio.invested_usd), foot: `Market value ${money(portfolio.market_value)}` },
  ];
}

function secondaryTiles(portfolio, performance) {
  const daily = num(portfolio.daily_pnl);
  return [
    { label: "Daily P&L", value: el("span", { class: daily >= 0 ? "pos" : "neg", text: `${daily >= 0 ? "+" : ""}${money(daily)}` }), foot: `Realized ${money(portfolio.daily_realized_pnl)}` },
    { label: "Unrealized", value: el("span", { class: num(portfolio.unrealized_pnl) >= 0 ? "pos" : "neg", text: `+${money(portfolio.unrealized_pnl)}` }), foot: "open positions only" },
    { label: "Win rate", value: pct(portfolio.win_rate, 1), foot: `${portfolio.wins}W / ${portfolio.losses}L` },
    { label: "Profit factor", value: performance && performance.profit_factor != null ? String(performance.profit_factor) : "—", foot: performance ? `${performance.trades} closed trades` : "no closed trades" },
  ];
}

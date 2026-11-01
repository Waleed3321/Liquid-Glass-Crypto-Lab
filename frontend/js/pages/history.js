/* Trade history: orders, simulated fills and closed positions with CSV export. */

import { api } from "../api.js";
import { callout, el, loadingRows, panel, tabs, toast } from "../ui.js";
import { csv, downloadCsv, humanizeCode, money, num, pct, price, signClass } from "../format.js";
import {
  chainCell,
  listen,
  onGlobalRefresh,
  poll,
  REFRESH_MS,
  sideBadge,
  statusBadge,
  timeCell,
  tokenIdentity,
} from "./shared.js";

const TABS = [
  { value: "orders", label: "Orders" },
  { value: "fills", label: "Fills" },
  { value: "positions", label: "Closed positions" },
];

function moneySigned(value, digits = 2) {
  const n = num(value);
  return el("span", {
    class: `numeric ${signClass(n)}`,
    text: `${n > 0 ? "+" : n < 0 ? "-" : ""}${money(Math.abs(n), digits)}`,
  });
}

function orderRow(order) {
  return {
    id: order.id,
    token_id: order.token_id,
    symbol: order.symbol,
    side: order.side,
    status: order.status,
    source: order.source,
    requested: num(order.requested_notional),
    qty: num(order.qty),
    fill_price: order.fill_price,
    fill_notional: order.fill_notional,
    code: order.reject_code,
    reason: order.reason,
    client_order_id: order.client_order_id,
    exit_key: order.exit_key,
    created_at: order.filled_at || order.created_at,
  };
}

function ordersTable(rows) {
  if (!rows.length) {
    return panel({ body: el("div", { class: "empty" }, el("div", { class: "empty-icon", text: "◇" }), el("p", { class: "muted", text: "No orders match the current filters." })) });
  }
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", { scope: "col", text: "Time" }),
          el("th", { scope: "col", text: "Token" }),
          el("th", { scope: "col", text: "Side" }),
          el("th", { scope: "col", text: "Status" }),
          el("th", { class: "right", scope: "col", text: "Requested" }),
          el("th", { class: "right", scope: "col", text: "Filled qty" }),
          el("th", { class: "right", scope: "col", text: "Fill price" }),
          el("th", { class: "right", scope: "col", text: "Fill notional" }),
          el("th", { scope: "col", text: "Key / reason" }),
          el("th", { scope: "col", text: "Source" }),
        ),
      ),
      el(
        "tbody",
        {},
        ...rows.map((order) =>
          el(
            "tr",
            {},
            el("td", {}, timeCell(order.created_at)),
            el("td", {}, tokenIdentity({ id: order.token_id, symbol: order.symbol, name: "" }, { sub: false })),
            el("td", {}, sideBadge(order.side)),
            el("td", {}, statusBadge(order.status)),
            el("td", { class: "right numeric", text: money(order.requested) }),
            el("td", { class: "right numeric", text: num(order.qty).toLocaleString(undefined, { maximumFractionDigits: 6 }) }),
            el("td", { class: "right numeric", text: order.fill_price != null ? price(order.fill_price) : "—" }),
            el("td", { class: "right numeric", text: order.fill_notional != null ? money(order.fill_notional) : "—" }),
            el(
              "td",
              {},
              order.code
                ? el("span", { class: "badge badge-fail", text: humanizeCode(order.code) })
                : el("span", { class: "numeric muted", text: order.exit_key || order.client_order_id || "—", title: order.reason || "" }),
            ),
            el("td", { class: "muted", text: order.source || "—" }),
          ),
        ),
      ),
    ),
  );
}

function fillsTable(rows) {
  if (!rows.length) {
    return panel({ body: el("div", { class: "empty" }, el("div", { class: "empty-icon", text: "◇" }), el("p", { class: "muted", text: "No simulated fills recorded yet." })) });
  }
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", { scope: "col", text: "Time" }),
          el("th", { scope: "col", text: "Token" }),
          el("th", { scope: "col", text: "Side" }),
          el("th", { class: "right", scope: "col", text: "Price" }),
          el("th", { class: "right", scope: "col", text: "Qty" }),
          el("th", { class: "right", scope: "col", text: "Notional" }),
          el("th", { class: "right", scope: "col", text: "Fees (est.)" }),
          el("th", { class: "right", scope: "col", text: "Slippage" }),
          el("th", { class: "right", scope: "col", text: "Impact" }),
          el("th", { class: "right", scope: "col", text: "Realized" }),
        ),
      ),
      el(
        "tbody",
        {},
        ...rows.map((fill) =>
          el(
            "tr",
            {},
            el("td", {}, timeCell(fill.created_at)),
            el("td", {}, tokenIdentity({ id: fill.order_id, symbol: fill.symbol, name: "" }, { sub: false })),
            el("td", {}, sideBadge(fill.side)),
            el(
              "td",
              {},
              el(
                "span",
                { class: "sym" },
                el("strong", { text: fill.symbol || "—" }),
                el("span", { text: fill.chain || "" }),
              ),
            ),
            el("td", { class: "right numeric", text: price(fill.price) }),
            el("td", { class: "right numeric", text: num(fill.qty).toLocaleString(undefined, { maximumFractionDigits: 6 }) }),
            el("td", { class: "right numeric", text: money(fill.notional) }),
            el("td", { class: "right numeric", text: money(fill.fee_total, 4), title: `network ${money(fill.fee_network, 4)} · dex ${money(fill.fee_dex, 4)} · tax ${money(fill.fee_tax, 4)}` }),
            el("td", { class: "right numeric", text: pct(fill.slippage_pct) }),
            el("td", { class: "right numeric", text: pct(fill.impact_pct) }),
            el("td", { class: "right" }, fill.side === "SELL" ? moneySigned(fill.realized_pnl) : el("span", { class: "muted", text: "—" })),
          ),
        ),
      ),
    ),
  );
}

function positionsTable(rows) {
  if (!rows.length) {
    return panel({ body: el("div", { class: "empty" }, el("div", { class: "empty-icon", text: "◇" }), el("p", { class: "muted", text: "No closed positions yet." })) });
  }
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", { scope: "col", text: "Closed" }),
          el("th", { scope: "col", text: "Token" }),
          el("th", { scope: "col", text: "Chain" }),
          el("th", { class: "right", scope: "col", text: "Entry" }),
          el("th", { scope: "col", text: "Exit" }),
          el("th", { class: "right", scope: "col", text: "Realized" }),
          el("th", { class: "right", scope: "col", text: "Fees" }),
          el("th", { scope: "col", text: "Strategy" }),
        ),
      ),
      el(
        "tbody",
        {},
        ...rows.map((position) =>
          el(
            "tr",
            {},
            el("td", {}, timeCell(position.closed_at)),
            el("td", {}, tokenIdentity({ ...position, id: position.token_id }, { sub: false })),
            el("td", {}, chainCell(position.chain)),
            el("td", { class: "right numeric", text: price(position.entry_price) }),
            el("td", { class: "muted", text: position.exit_reason ? humanizeCode(position.exit_reason) : "—" }),
            el("td", { class: "right" }, moneySigned(position.realized_pnl)),
            el("td", { class: "right numeric", text: money(position.fees_paid, 4) }),
            el("td", { class: "muted numeric", text: position.strategy_version || "—" }),
          ),
        ),
      ),
    ),
  );
}

export default {
  title: "Trade History",
  crumb: "Paper book",
  async render(ctx) {
    const page = el("div", { class: "stack" });
    const head = el(
      "div",
      { class: "page-head" },
      el(
        "div",
        {},
        el("span", { class: "label", text: "Paper book" }),
        el("h2", { text: "Trade history" }),
        el("p", {
          class: "muted",
          text: "Orders, simulated fills and closed positions. Fees, slippage, impact and tax are labelled estimates — nothing here touched a chain.",
        }),
      ),
    );

    const metrics = el("div", { class: "grid" });
    const filters = el("div", { class: "filter-bar" });
    const tabsRow = el("div", { class: "row-between" });
    const body = el("div", { class: "stack" }, loadingRows(3));
    page.append(head, metrics, callout({ tone: "warning", title: "Simulation only", children: "Every fill is model output based on the latest market snapshot. No wallet, signature or real funds are involved." }), tabsRow, filters, body);

    const search = el("input", { class: "input", type: "search", placeholder: "Filter by symbol or address…", "aria-label": "Filter trades" });
    const sideSelect = el(
      "select",
      { class: "select", "aria-label": "Filter by side", style: { maxWidth: "150px" } },
      el("option", { value: "", text: "All sides" }),
      el("option", { value: "BUY", text: "Buys" }),
      el("option", { value: "SELL", text: "Sells" }),
      el("option", { value: "REJECTED", text: "Rejected" }),
    );

    let view = "orders";
    let data = { orders: [], fills: [], positions: [] };
    let query = "";
    let side = "";

    const rowsFor = () => {
      const needle = query.trim().toLowerCase();
      const matchSide = (row) => {
        if (!side) return true;
        if (side === "REJECTED") return String(row.status || "").toUpperCase() === "REJECTED";
        return String(row.side || "").toUpperCase() === side;
      };
      const matchText = (row) =>
        !needle || `${row.symbol || ""} ${row.reason || ""} ${row.code || ""}`.toLowerCase().includes(needle);

      if (view === "orders") return data.orders.map(orderRow).filter((row) => matchSide(row) && matchText(row));
      if (view === "fills") return data.fills.filter((row) => matchSide(row) && matchText(row));
      return data.positions.filter((row) => {
        if (!needle) return true;
        return `${row.symbol || ""} ${row.address || ""} ${row.exit_reason || ""}`.toLowerCase().includes(needle);
      });
    };

    const columnsForCsv = () =>
      view === "orders"
        ? [
            { label: "time", value: (row) => row.created_at || "" },
            { label: "symbol", value: (row) => row.symbol || "" },
            { label: "side", value: (row) => row.side || "" },
            { label: "status", value: (row) => row.status || "" },
            { label: "requested_usd", value: (row) => row.requested },
            { label: "qty", value: (row) => row.qty },
            { label: "fill_price", value: (row) => row.fill_price ?? "" },
            { label: "fill_notional", value: (row) => row.fill_notional ?? "" },
            { label: "reject_code", value: (row) => row.code || "" },
            { label: "reason", value: (row) => row.reason || "" },
          ]
        : view === "fills"
          ? [
              { label: "time", value: (row) => row.created_at || "" },
              { label: "symbol", value: (row) => row.symbol || "" },
              { label: "side", value: (row) => row.side || "" },
              { label: "price", value: (row) => row.price },
              { label: "qty", value: (row) => row.qty },
              { label: "notional", value: (row) => row.notional },
              { label: "fee_total", value: (row) => row.fee_total },
              { label: "slippage_pct", value: (row) => row.slippage_pct },
              { label: "impact_pct", value: (row) => row.impact_pct },
              { label: "realized_pnl", value: (row) => row.realized_pnl },
            ]
          : [
              { label: "closed_at", value: (row) => row.closed_at || "" },
              { label: "symbol", value: (row) => row.symbol || "" },
              { label: "chain", value: (row) => row.chain || "" },
              { label: "entry_price", value: (row) => row.entry_price },
              { label: "exit_reason", value: (row) => row.exit_reason || "" },
              { label: "realized_pnl", value: (row) => row.realized_pnl },
              { label: "fees_paid", value: (row) => row.fees_paid },
            ];

    const exportCsv = () => {
      const rows = rowsFor();
      if (!rows.length) {
        toast({ title: "Nothing to export", message: "No rows match the current filters.", type: "warning" });
        return;
      }
      downloadCsv(`paper-${view}-${new Date().toISOString().slice(0, 10)}.csv`, csv(rows, columnsForCsv()));
      toast({ title: "Export ready", message: `${rows.length} rows written to CSV.`, type: "success" });
    };

    const renderTabs = () => {
      tabsRow.replaceChildren(
        tabs(TABS, {
          active: view,
          onChange: (value) => {
            view = value;
            renderTabs();
            renderBody();
          },
        }),
        el("span", { class: "result-count", text: `${rowsFor().length} rows` }),
      );
    };

    const renderFilters = () => {
      filters.replaceChildren(
        el("div", { class: "search grow" }, search),
        sideSelect,
        el("button", { class: "btn btn-sm", type: "button", text: "Export CSV", onClick: exportCsv }),
      );
      if (view === "positions") {
        sideSelect.disabled = true;
      } else {
        sideSelect.disabled = false;
      }
    };

    const renderBody = () => {
      const rows = rowsFor();
      if (view === "orders") body.replaceChildren(ordersTable(rows));
      else if (view === "fills") body.replaceChildren(fillsTable(rows));
      else body.replaceChildren(positionsTable(rows));
      renderTabs();
    };

    const renderMetrics = () => {
      const orders = data.orders;
      const fills = data.fills;
      const rejected = orders.filter((order) => String(order.status).toUpperCase() === "REJECTED").length;
      const realized = fills.reduce((sum, fill) => sum + num(fill.realized_pnl), 0);
      const fees = fills.reduce((sum, fill) => sum + num(fill.fee_total), 0);
      metrics.replaceChildren(
        ...[
          { label: "Orders", value: String(orders.length), foot: `${rejected} rejected` },
          { label: "Fills", value: String(fills.length), foot: "simulated executions" },
          { label: "Fees paid", value: money(fees, 4), foot: "network + DEX + tax (est.)" },
          {
            label: "Realized P&L",
            value: el("span", { class: realized >= 0 ? "pos" : "neg", text: `${realized > 0 ? "+" : realized < 0 ? "-" : ""}${money(Math.abs(realized))}` }),
            foot: "closed exits only",
          },
        ].map((item) =>
          el(
            "div",
            { class: "col-3" },
            el(
              "div",
              { class: "stat glass edge-light" },
              el("span", { class: "stat-label", text: item.label }),
              el("div", { class: "stat-value" }, item.value),
              el("div", { class: "stat-foot" }, el("span", { class: "muted", text: item.foot })),
            ),
          ),
        ),
      );
    };

    async function refresh() {
      try {
        const payload = await api.tradeHistory({ limit: 300 });
        if (!ctx.isActive()) return;
        data = {
          orders: payload.orders || [],
          fills: payload.fills || [],
          positions: payload.positions || [],
        };
        renderMetrics();
        renderFilters();
        renderBody();
      } catch (error) {
        if (error.name === "AbortError" || !ctx.isActive()) return;
        body.replaceChildren(callout({ tone: "danger", title: "History unavailable", children: error.message }));
      }
    }

    const applyFilter = () => {
      query = search.value;
      side = sideSelect.value;
      renderBody();
    };
    search.addEventListener("input", applyFilter);
    sideSelect.addEventListener("change", applyFilter);

    renderTabs();
    await refresh();
    poll(ctx, REFRESH_MS * 2, refresh);
    listen(ctx, ["trade"], refresh);
    onGlobalRefresh(ctx, refresh);

    return page;
  },
};

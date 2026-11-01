/* Open positions: capacity, risk guardrails, live P&L and simulated exits. */

import { api } from "../api.js";
import { badge, callout, el, empty, loadingRows, panel, statTile, tabs, toastError } from "../ui.js";
import { money, num, pct, price, signClass, timeAgo } from "../format.js";
import {
  chainCell,
  limitMeters,
  listen,
  onGlobalRefresh,
  openSellSheet,
  poll,
  REFRESH_MS,
  securityBadge,
  tokenIdentity,
} from "./shared.js";

const CAPACITY = 3;

function stat(label, value, className = "") {
  return el(
    "div",
    { class: "pos-stat" },
    el("span", { text: label }),
    el("strong", { class: className, text: value }),
  );
}

function level(label, value, tone = "") {
  return el(
    "div",
    { class: "pos-level" },
    el("span", { text: label }),
    el("strong", { class: tone, text: value }),
  );
}

function slots(used, cap) {
  const dots = el("span", { class: "slots", "aria-hidden": "true" });
  for (let index = 0; index < cap; index += 1) {
    dots.append(el("i", { class: index < used ? "on" : "" }));
  }
  return el(
    "div",
    { class: "row", style: { gap: "10px" } },
    dots,
    el("span", { class: "muted numeric", text: `${used} of ${cap} slots used` }),
  );
}

function pnlCell(value, digits = 2) {
  const n = num(value);
  return el("span", {
    class: `numeric ${signClass(n)}`,
    text: `${n > 0 ? "+" : n < 0 ? "-" : ""}${money(Math.abs(n), digits)}`,
  });
}

function openCard(position, ctx, refresh) {
  const pnl = num(position.unrealized_pnl);
  const pnlPct = num(position.unrealized_pct);
  const head = el(
    "div",
    { class: "pos-head" },
    tokenIdentity(position),
    chainCell(position.chain),
    position.protection_armed ? badge("PASS", "Protected") : null,
  );

  const actions = el(
    "div",
    { class: "pos-actions" },
    el("button", {
      class: "btn btn-sm btn-ghost",
      type: "button",
      text: "Details",
      onClick: () => ctx.navigate(`token/${position.token_id}`),
    }),
    el("button", {
      class: "btn btn-sm btn-danger",
      type: "button",
      text: "Sell 50%",
      onClick: async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
          await api.sell({ position_id: position.id, ratio: 0.5 });
          refresh();
        } catch (error) {
          toastError(error);
          button.disabled = false;
        }
      },
    }),
    el("button", {
      class: "btn btn-sm",
      type: "button",
      text: "Manage",
      onClick: () => openSellSheet(position, { onDone: refresh }),
    }),
  );

  const card = el(
    "article",
    { class: "position-card" },
    head,
    stat("Remaining", `${num(position.remaining_qty).toLocaleString(undefined, { maximumFractionDigits: 6 })} ${position.symbol || ""}`),
    stat("Market value", money(position.market_value), "pos"),
    el(
      "div",
      { class: "pos-stat" },
      el("span", { text: "Unrealized" }),
      el("strong", { class: pnl >= 0 ? "pos" : "neg", text: `${pnl >= 0 ? "+" : "-"}${money(Math.abs(pnl))} (${pct(pnlPct)})` }),
    ),
    actions,
  );

  const stop = position.stop_price != null ? price(position.stop_price) : "not set";
  const trail = num(position.trail_high) > 0 ? price(position.trail_high) : "—";
  const strip = el(
    "div",
    { class: "pos-strip" },
    level("Entry", price(position.entry_price)),
    level("Market", price(position.market_price)),
    level("Invested", money(position.invested_usd)),
    level("Peak", price(position.peak_price)),
    level("Trail high", trail),
    level("Stop", stop, "neg"),
    level("Entry fees", money(position.entry_fees, 4)),
    level("Snapshot", position.price_age_seconds != null ? `${Math.round(num(position.price_age_seconds))}s old` : "—", num(position.price_age_seconds) > 120 ? "neg" : ""),
    el("span", { class: "grow" }),
    securityBadge(position.security_status ? { overall: position.security_status } : null),
    el("span", { class: "muted", text: `opened ${timeAgo(position.opened_at)}` }),
  );

  return el("div", { class: "panel glass", style: { padding: "0", gap: "0" } }, card, strip);
}

function openList(items, ctx, refresh) {
  if (!items.length) {
    return panel({
      title: "Open positions",
      body: empty({
        icon: "◇",
        title: "No open paper positions",
        message:
          "Entries only fire when every gate passes: score, confidence, security, observation window, pullback, liquidity and the 1% impact limit. Nothing is forced.",
        action: el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "Open the scanner",
          onClick: () => ctx.navigate("scanner"),
        }),
      }),
    });
  }
  return el("div", { class: "stack" }, ...items.map((position) => openCard(position, ctx, refresh)));
}

function closedTable(items) {
  if (!items.length) {
    return panel({
      title: "Closed positions",
      body: empty({ icon: "◌", title: "No closed positions yet", message: "Exits appear here with their reason and realized P&L." }),
    });
  }
  const rows = items.map((position) => {
    const pnl = num(position.realized_pnl);
    return el(
      "tr",
      {},
      el("td", {}, tokenIdentity(position, { sub: false })),
      el("td", {}, chainCell(position.chain)),
      el("td", { class: "right numeric", text: price(position.entry_price) }),
      el("td", { text: position.exit_reason ? String(position.exit_reason).replace(/_/g, " ") : "—" }),
      el("td", { class: "right" }, pnlCell(pnl)),
      el(
        "td",
        { class: "right numeric" },
        el("span", { text: num(position.remaining_qty).toLocaleString(undefined, { maximumFractionDigits: 6 }) }),
      ),
      el("td", { class: "right" }, el("span", { class: "numeric", text: timeAgo(position.closed_at), title: position.closed_at || "" })),
    );
  });
  return panel({
    title: "Closed positions",
    subtitle: "Every exit is a simulated fill — never a chain transaction.",
    body: el(
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
            el("th", { scope: "col", text: "Token" }),
            el("th", { scope: "col", text: "Chain" }),
            el("th", { class: "right", scope: "col", text: "Entry" }),
            el("th", { scope: "col", text: "Exit reason" }),
            el("th", { class: "right", scope: "col", text: "Realized" }),
            el("th", { class: "right", scope: "col", text: "Qty at close" }),
            el("th", { class: "right", scope: "col", text: "Closed" }),
          ),
        ),
        el("tbody", {}, ...rows),
      ),
    ),
  });
}

export default {
  title: "Open Positions",
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
        el("h2", { text: "Open positions" }),
        el("p", {
          class: "muted",
          text: "Maximum three concurrent positions, $2.50 per entry and a $0.50 daily loss budget — enforced in one database transaction.",
        }),
      ),
      el(
        "div",
        { class: "page-actions" },
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "Find a setup",
          onClick: () => ctx.navigate("scanner"),
        }),
      ),
    );

    const metaTiles = el("div", { class: "grid" });
    const guardrails = el("div", { class: "panel glass" });
    const body = el("div", { class: "stack" }, loadingRows(2));
    const controls = el("div", { class: "row-between" });
    page.append(head, metaTiles, guardrails, controls, body);

    let view = "open";
    let summary = null;
    let openItems = [];
    let closedItems = [];

    const renderBody = () => {
      if (view === "open") {
        body.replaceChildren(openList(openItems, ctx, refresh));
        return;
      }
      body.replaceChildren(closedTable(closedItems));
    };

    const renderTabs = () => {
      controls.replaceChildren(
        tabs(
          [
            { value: "open", label: `Open (${openItems.length})` },
            { value: "closed", label: `Closed (${closedItems.length})` },
          ],
          {
            active: view,
            onChange: (value) => {
              view = value;
              renderTabs();
              renderBody();
            },
          },
        ),
        el("span", { class: "result-count", text: summary ? `${summary.open_positions}/${summary.max_open_positions} slots occupied` : "" }),
      );
    };

    const renderSummary = () => {
      if (!summary) return;
      const total = num(summary.total_pnl);
      metaTiles.replaceChildren(
        el("div", { class: "col-3" }, statTile({
          label: "Open positions",
          value: el(
            "span",
            {},
            String(summary.open_positions),
            el("small", { text: `/ ${summary.max_open_positions}` }),
          ),
          foot: slots(num(summary.open_positions), num(summary.max_open_positions, CAPACITY)),
        })),
        el("div", { class: "col-3" }, statTile({
          label: "Invested",
          value: money(summary.invested_usd),
          foot: el("span", { class: "muted", text: `market value ${money(summary.market_value)}` }),
        })),
        el("div", { class: "col-3" }, statTile({
          label: "Unrealized P&L",
          value: el("span", { class: total >= 0 ? "" : "neg", text: `${num(summary.unrealized_pnl) >= 0 ? "+" : "-"}${money(Math.abs(num(summary.unrealized_pnl)))}` }),
          foot: el("span", { class: "muted", text: `${num(summary.unrealized_pnl) >= 0 ? "+" : ""}${pct(summary.invested_usd ? (num(summary.unrealized_pnl) / num(summary.invested_usd)) * 100 : 0)} on invested` }),
        })),
        el("div", { class: "col-3" }, statTile({
          label: "Realized today",
          value: el("span", { class: num(summary.daily_realized_pnl) >= 0 ? "pos" : "neg", text: money(summary.daily_realized_pnl) }),
          foot: el("span", { class: "muted", text: `budget left ${money(summary.daily_loss_remaining)}` }),
        })),
      );
      guardrails.replaceChildren(
        el(
          "div",
          { class: "panel-head" },
          el(
            "div",
            { class: "panel-title" },
            el("h3", { text: "Risk guardrails" }),
            el("p", { text: "Live values read from the paper account, not the browser." }),
          ),
          summary.halted ? badge("FAIL", "Trading halted") : badge("PASS", "Trading allowed"),
        ),
        limitMeters(summary),
        summary.halted
          ? callout({
              tone: "danger",
              title: "New entries are halted",
              children: "The daily loss budget was exhausted for the current trading day. Exits remain available; entries resume at the next UTC rollover.",
            })
          : callout({
              tone: "info",
              title: "Server-side enforcement",
              children: "Position count, notional cap, cash, daily loss, freshness, security and impact checks all run inside a single transaction with an advisory lock.",
            }),
      );
    };

    async function refresh() {
      try {
        const [portfolio, open, closed] = await Promise.all([
          api.portfolio(),
          api.positions(),
          api.positions({ history: true, limit: 50 }),
        ]);
        if (!ctx.isActive()) return;
        summary = portfolio;
        openItems = open.positions || [];
        closedItems = closed.positions || [];
        renderSummary();
        renderTabs();
        renderBody();
      } catch (error) {
        if (error.name === "AbortError" || !ctx.isActive()) return;
        body.replaceChildren(
          callout({
            tone: "danger",
            title: "Positions unavailable",
            children: (error && error.message) || "The paper book could not be loaded.",
          }),
        );
      }
    }

    renderTabs();
    await refresh();
    poll(ctx, REFRESH_MS, refresh);
    listen(ctx, ["trade", "scanner"], refresh);
    onGlobalRefresh(ctx, refresh);

    return page;
  },
};

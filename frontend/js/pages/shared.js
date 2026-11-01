/* Shared page building blocks: token identity, badges, meters and live helpers. */

import { badge, callout, chainBadge, el, empty, field, input, meter, modal, scorePill, statTile, toast, toastError, tokenAvatar } from "../ui.js";
import { api } from "../api.js";
import { money, num, pct, price, shortAddress, signClass, timeAgo } from "../format.js";
import { onEvent } from "../sse.js";

export const REFRESH_MS = (window.LAB_CONFIG && window.LAB_CONFIG.refreshMs) || 30000;

export function tokenIdentity(row, { avatar = true, sub = true } = {}) {
  const meta = row.pair && row.pair.dex_id ? row.pair.dex_id : row.chain_label || "";
  return el(
    "a",
    { class: "token-link", href: `#/token/${row.id}`, "aria-label": `Open ${row.symbol || "token"} details` },
    avatar ? tokenAvatar(row.symbol, row.image_url) : null,
    el(
      "span",
      { class: "sym" },
      el("strong", { text: row.symbol || "—" }),
      sub ? el("span", { text: row.name || meta || shortAddress(row.address) }) : null,
    ),
  );
}

export function securityBadge(security) {
  const overall = security && security.overall ? security.overall : "UNKNOWN";
  const label = security ? overall : "NO DATA";
  const node = badge(overall, label);
  if (security) {
    node.title = `${security.critical_pass ?? 0}/${security.critical_total ?? 0} critical checks verified · risk ${num(
      security.risk_score,
    ).toFixed(0)}/100`;
  } else {
    node.title = "No security provider returned data. Automatic entry is blocked.";
  }
  return node;
}

export function scoreCell(score) {
  if (!score) return el("span", { class: "muted", text: "—" });
  return scorePill(score.score, score.confidence);
}

export function signalBadge(signal) {
  const value = String(signal || "HOLD").toUpperCase();
  const map = { ENTER: "ENTER", EXIT: "EXIT", REJECT: "REJECT", HOLD: "HOLD", WATCH: "HOLD" };
  return badge(value, map[value] || value);
}

export function sideBadge(side) {
  const value = String(side || "").toUpperCase();
  return badge(value === "BUY" ? "ENTER" : "EXIT", value || "—");
}

export function statusBadge(status) {
  const value = String(status || "UNKNOWN").toUpperCase();
  return badge(value, value.replace(/_/g, " "));
}

export function ageCell(minutes) {
  const value = num(minutes);
  if (!Number.isFinite(value) || value <= 0) return el("span", { class: "muted", text: "—" });
  if (value < 60) return el("span", { class: "numeric", text: `${Math.round(value)}m` });
  if (value < 1440) return el("span", { class: "numeric", text: `${(value / 60).toFixed(1)}h` });
  return el("span", { class: "numeric", text: `${(value / 1440).toFixed(1)}d` });
}

export function priceCell(value) {
  return el("span", { class: "numeric", text: price(value) });
}

export function changeCell(value) {
  const n = num(value);
  return el("span", { class: `numeric ${signClass(n)}`, text: `${n > 0 ? "+" : n < 0 ? "-" : ""}${Math.abs(n).toFixed(2)}%` });
}

export function usdCell(value, digits = 2) {
  return el("span", { class: "numeric", text: money(value, digits) });
}

export function statTiles(items) {
  return el(
    "div",
    { class: "grid" },
    ...items.map((item) => el("div", { class: item.span || "col-3" }, statTile(item))),
  );
}

export function limitMeters(summary) {
  const open = num(summary.open_positions);
  const cap = num(summary.max_open_positions, 3);
  const lossUsed = num(summary.daily_loss_used);
  const lossLimit = num(summary.daily_loss_limit, 0.5);
  const cash = num(summary.cash_balance);
  const largest = (summary.positions || []).reduce((max, position) => Math.max(max, num(position.entry_notional)), 0);
  return el(
    "div",
    { class: "stack", style: { gap: "18px" } },
    meter({
      label: "Open position slots",
      value: open,
      max: cap,
      text: `${open}/${cap}`,
      tone: open >= cap ? "danger" : "mint",
    }),
    meter({
      label: "Daily loss budget",
      value: lossUsed,
      max: lossLimit,
      text: `$${lossUsed.toFixed(2)} / $${lossLimit.toFixed(2)}`,
      tone: lossUsed >= lossLimit * 0.8 ? "danger" : lossUsed > 0 ? "amber" : "mint",
    }),
    meter({
      label: "Largest position vs $2.50 cap",
      value: largest,
      max: 2.5,
      text: `$${largest.toFixed(2)} / $2.50`,
      tone: largest >= 2.5 ? "amber" : "",
    }),
    meter({
      label: "Cash available",
      value: cash,
      max: num(summary.initial_balance, 10),
      text: `$${cash.toFixed(2)}`,
      tone: "mint",
    }),
  );
}

export function copyButton(text, label = "Copy") {
  if (!text) return null;
  return el("button", {
    class: "btn btn-xs btn-ghost",
    type: "button",
    title: `Copy ${text}`,
    text: label,
    onClick: async () => {
      try {
        await navigator.clipboard.writeText(text);
        toast({ title: "Copied", message: text, type: "success", timeout: 2000 });
      } catch {
        toast({
          title: "Clipboard unavailable",
          message: text,
          type: "warning",
        });
      }
    },
  });
}

export function fieldRow(label, value) {
  return el("div", { class: "row-between" }, el("span", { class: "muted", text: label }), el("strong", { class: "numeric", text: value }));
}

export function inlineError(node, error, retry) {
  const message = (error && error.message) || "The request failed.";
  node.replaceChildren(
    callout({
      tone: "danger",
      title: (error && error.code ? String(error.code).replace(/_/g, " ") : "Request failed").toLowerCase(),
      children: message,
    }),
    retry ? el("div", { class: "row" }, el("button", { class: "btn btn-sm", type: "button", text: "Retry", onClick: retry })) : null,
  );
}

export function listen(ctx, types, handler) {
  for (const type of types) {
    ctx.onCleanup(onEvent(type, handler));
  }
}

export function poll(ctx, ms, fn) {
  const timer = setInterval(fn, ms);
  ctx.onCleanup(() => clearInterval(timer));
  return timer;
}

export function onGlobalRefresh(ctx, fn) {
  window.addEventListener("lab:refresh", fn);
  ctx.onCleanup(() => window.removeEventListener("lab:refresh", fn));
}

export function staleNote(seconds, limitSeconds = 120) {
  if (seconds == null) return el("span", { class: "muted", text: "no snapshot" });
  const value = num(seconds);
  const fresh = value <= limitSeconds;
  return el("span", {
    class: fresh ? "muted" : "neg",
    text: `${Math.round(value)}s old`,
    title: fresh ? "Snapshot is fresh" : `Older than the ${limitSeconds}s freshness gate`,
  });
}

export function emptyPanel({ title, message, icon = "◇", action }) {
  return el("div", { class: "panel glass" }, empty({ icon, title, message, action }));
}

export function reasonChips(codes, limit = 4) {
  const list = (codes || []).slice(0, limit);
  if (!list.length) return el("span", { class: "muted", text: "—" });
  return el(
    "span",
    { class: "inline-list" },
    ...list.map((code) =>
      el("span", { class: "badge badge-unknown", text: String(code).replace(/_/g, " ").toLowerCase() }),
    ),
  );
}

export function timeCell(iso) {
  const node = el("span", { class: "numeric", text: timeAgo(iso) });
  node.title = iso || "";
  return node;
}

export function pctCellValue(value, digits = 2) {
  return el("span", { class: `numeric ${signClass(num(value))}`, text: `${num(value) > 0 ? "+" : ""}${pct(value, digits)}` });
}

export function chainCell(chain) {
  return chainBadge(chain);
}

export function newClientOrderId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function openBuySheet(row, { onDone } = {}) {
  const amount = input({
    type: "number",
    min: "0.1",
    max: "2.5",
    step: "0.1",
    value: "2.50",
    "aria-label": "Notional in US dollars",
  });
  const note = el("div", { class: "hint" });
  const updateNote = () => {
    const value = num(amount.value);
    note.textContent =
      value > 2.5
        ? "The backend caps a new position at $2.50 and will reject this order."
        : "Simulated fill at the latest snapshot, including impact (max 1%), slippage, network/DEX fees and token tax where known.";
  };
  amount.addEventListener("input", updateNote);
  updateNote();
  const footer = el(
    "div",
    { class: "row" },
    el("button", { class: "btn", type: "button", text: "Cancel", onClick: () => sheet.close() }),
    el("button", {
      class: "btn btn-primary",
      type: "button",
      text: "Execute paper buy",
      onClick: async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
          const result = await api.buy({
            token_id: row.id,
            notional_usd: num(amount.value),
            client_order_id: newClientOrderId(),
          });
          sheet.close();
          toast({
            title: result.duplicate ? "Duplicate order replayed" : "Paper buy filled",
            message: `${row.symbol || "Token"} · ${money(result.fill_notional)} at ${price(result.fill_price)} · fees ${money(
              result.fees ? result.fees.total : 0,
              4,
            )} · cash ${money(result.cash_balance)}`,
            type: "success",
            timeout: 6000,
          });
          window.dispatchEvent(new CustomEvent("lab:trade"));
          onDone?.(result);
        } catch (error) {
          toastError(error);
          button.disabled = false;
        }
      },
    }),
  );
  const sheet = modal({
    title: `Paper buy · ${row.symbol || "token"}`,
    subtitle: "Simulated execution only — no wallet, no signature, no real funds.",
    body: el(
      "div",
      { class: "stack" },
      el(
        "div",
        { class: "row wrap" },
        ...[1, 2, 2.5].map((value) =>
          el("button", {
            class: "btn btn-sm",
            type: "button",
            text: money(value),
            onClick: () => {
              amount.value = String(value);
              updateNote();
            },
          }),
        ),
      ),
      field({ label: "Notional (USD)", control: amount, hint: "Starting balance $10.00 · max $2.50 per new position." }),
      note,
      callout({
        tone: "info",
        title: "Risk checks run server-side",
        children:
          "Open-position count, notional cap, cash, daily loss, snapshot freshness, security eligibility and the 1% impact limit are enforced inside one transaction.",
      }),
    ),
    footer,
  });
  return sheet;
}

export function openSellSheet(position, { onDone } = {}) {
  let ratio = 1;
  const note = el("div", { class: "hint" });
  const chips = el("div", { class: "row wrap" });
  const renderChips = () => {
    chips.replaceChildren(
      ...[0.25, 0.5, 0.75, 1].map((value) =>
        el("button", {
          class: `btn btn-sm ${ratio === value ? "btn-primary" : ""}`.trim(),
          type: "button",
          text: value === 1 ? "Sell all" : `Sell ${Math.round(value * 100)}%`,
          onClick: () => {
            ratio = value;
            renderChips();
            updateNote();
          },
        }),
      ),
    );
  };
  const updateNote = () => {
    const qty = num(position.remaining_qty) * ratio;
    note.textContent = `Simulated exit of ${qty.toLocaleString(undefined, {
      maximumFractionDigits: 6,
    })} ${position.symbol || "tokens"} at the latest snapshot, minus slippage, fees and sell tax.`;
  };
  renderChips();
  updateNote();
  const footer = el(
    "div",
    { class: "row" },
    el("button", { class: "btn", type: "button", text: "Cancel", onClick: () => sheet.close() }),
    el("button", {
      class: "btn btn-danger",
      type: "button",
      text: "Execute paper sell",
      onClick: async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
          const result = await api.sell({ position_id: position.id, ratio });
          sheet.close();
          toast({
            title: "Paper sell filled",
            message: `${position.symbol || "Token"} · ${money(result.proceeds_usd)} proceeds · realized ${money(
              result.realized_pnl,
            )} · remaining ${num(result.remaining_qty).toLocaleString(undefined, { maximumFractionDigits: 6 })}`,
            type: "success",
            timeout: 6000,
          });
          window.dispatchEvent(new CustomEvent("lab:trade"));
          onDone?.(result);
        } catch (error) {
          toastError(error);
          button.disabled = false;
        }
      },
    }),
  );
  const sheet = modal({
    title: `Paper sell · ${position.symbol || "position"}`,
    subtitle: "Simulated exit. The backend clamps quantity to the remaining position.",
    body: el(
      "div",
      { class: "stack" },
      chips,
      note,
      el(
        "dl",
        { class: "kv" },
        el("dt", { text: "Remaining quantity" }),
        el("dd", { text: num(position.remaining_qty).toLocaleString(undefined, { maximumFractionDigits: 6 }) }),
        el("dt", { text: "Entry price" }),
        el("dd", { text: price(position.entry_price) }),
        el("dt", { text: "Market price" }),
        el("dd", { text: price(position.market_price) }),
        el("dt", { text: "Unrealized P&L" }),
        el("dd", { class: num(position.unrealized_pnl) >= 0 ? "pos" : "neg", text: money(position.unrealized_pnl) }),
      ),
      callout({
        tone: "info",
        title: "Idempotent exits",
        children: "Automatic exits use stable keys (tp50, tp100, stop, trail) so a retried tick can never sell twice.",
      }),
    ),
    footer,
  });
  return sheet;
}

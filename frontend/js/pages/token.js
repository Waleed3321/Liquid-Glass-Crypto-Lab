/* Token Details: market, score, security and the decision trail for one coin. */

import { api } from "../api.js";
import { duelChart } from "../charts.js";
import { clock, money, num, price, shortAddress, timeAgo } from "../format.js";
import {
  badge,
  callout,
  dataTable,
  el,
  empty,
  mount,
  pageHead,
  panel,
  progressRing,
  toast,
  toastError,
} from "../ui.js";
import {
  REFRESH_MS,
  ageCell,
  chainCell,
  changeCell,
  copyButton,
  listen,
  onGlobalRefresh,
  openBuySheet,
  poll,
  reasonChips,
  scoreCell,
  securityBadge,
  signalBadge,
  timeCell,
  usdCell,
} from "./shared.js";

const WEIGHTS = { liquidity: 25, volume: 20, activity: 15, holders: 15, momentum: 15, security: 10 };
const FIELD_ORDER = { FAIL: 0, WARNING: 1, UNKNOWN: 2, UNAVAILABLE: 3, PASS: 4 };

export default {
  title: "Token Details",
  crumb: "Research",
  render(ctx) {
    const id = Number(ctx.params[0]);
    if (!Number.isFinite(id) || id <= 0) {
      return el(
        "div",
        { class: "stack" },
        pageHead({ title: "Token Details", description: "Open a token from the scanner or watchlist." }),
        callout({ tone: "warning", title: "No token selected", children: "Choose a token from the scanner to see its details." }),
      );
    }

    const state = { token: null, history: null, hours: 6, watchBusy: false };

    const headerNode = el("div", {});
    const statsNode = el("div", {});
    const chartBody = el("div", {});
    const chartRange = el("div", { class: "row" });
    const marketBody = el("div", {});
    const scoreBody = el("div", {});
    const securityBody = el("div", {});
    const decisionsBody = el("div", {});
    const dataBody = el("div", {});

    const root = el(
      "div",
      { class: "stack" },
      headerNode,
      statsNode,
      panel({
        title: "Price and volume",
        subtitle: "Snapshots recorded by the independent scanner",
        actions: chartRange,
        body: chartBody,
      }),
      el("div", { class: "grid" }, el("div", { class: "col-7" }, panel({ title: "Opportunity score", subtitle: "Weighted 0–100 with data confidence", body: scoreBody })), el("div", { class: "col-5" }, panel({ title: "Market context", subtitle: "Pair, liquidity and links", body: marketBody }))),
      panel({
        title: "Security screening",
        subtitle: "Every field shows its verdict, raw value and provider. Missing data is never treated as safe.",
        actions: el("div", { class: "sec-legend" }),
        body: securityBody,
      }),
      panel({
        title: "Strategy decisions",
        subtitle: "Entry and exit evaluations for this token, including rejection reasons",
        body: decisionsBody,
      }),
      panel({
        title: "Snapshot history",
        subtitle: "Raw observations retained for the recent window",
        body: dataBody,
      }),
    );

    for (const node of [headerNode, statsNode, chartBody, marketBody, scoreBody, securityBody, decisionsBody, dataBody]) {
      mount(node, el("div", { class: "skeleton skeleton-row" }), el("div", { class: "skeleton skeleton-row" }));
    }

    [1, 6, 24].forEach((hours) => {
      chartRange.append(
        el("button", {
          class: `chip ${state.hours === hours ? "active" : ""}`.trim(),
          type: "button",
          text: hours === 1 ? "1h" : hours === 6 ? "6h" : "24h",
          onClick: () => {
            state.hours = hours;
            chartRange.querySelectorAll(".chip").forEach((chip) => chip.classList.remove("active"));
            chartRange.querySelectorAll(".chip")[hours === 1 ? 0 : hours === 6 ? 1 : 2].classList.add("active");
            loadHistory();
          },
        }),
      );
    });

    function renderHeader(token) {
      const actions = el(
        "div",
        { class: "detail-actions" },
        el("button", {
          class: `btn btn-sm ${token.in_watchlist ? "btn-success" : ""}`.trim(),
          type: "button",
          text: token.in_watchlist ? "★ Watching" : "☆ Watch",
          onClick: toggleWatch,
        }),
        token.has_position
          ? el("a", { class: "btn btn-sm btn-success", href: "#/positions", text: "Manage position" })
          : el("button", { class: "btn btn-sm btn-primary", type: "button", text: "Paper buy", onClick: () => openBuySheet(token, { onDone: load }) }),
        token.links && token.links.dexscreener
          ? el("a", { class: "btn btn-sm btn-ghost", href: token.links.dexscreener, target: "_blank", rel: "noopener", text: "DEX Screener ↗" })
          : null,
        token.links && token.links.explorer
          ? el("a", { class: "btn btn-sm btn-ghost", href: token.links.explorer, target: "_blank", rel: "noopener", text: "Explorer ↗" })
          : null,
      );

      const avatar = el("div", { class: "detail-avatar", "aria-hidden": "true", text: (token.symbol || "?").slice(0, 3).toUpperCase() });
      if (token.image_url) {
        const img = new Image();
        img.alt = "";
        img.loading = "lazy";
        img.src = token.image_url;
        img.onload = () => avatar.replaceChildren(img);
        avatar.append(img);
      }

      mount(
        headerNode,
        el(
          "section",
          { class: "panel glass" },
          el(
            "div",
            { class: "detail-head" },
            avatar,
            el(
              "div",
              { class: "detail-title" },
              el("h2", { text: token.symbol || "Unknown token" }),
              el(
                "div",
                { class: "sub" },
                chainCell(token.chain),
                el("span", { class: "mono", text: shortAddress(token.address, 8, 6) }),
                copyButton(token.address, "Copy"),
                el("span", { text: `· ${ageCell(token.age_minutes).textContent} old` }),
                el("span", { text: `· first seen ${timeAgo(token.first_discovered_at)}` }),
              ),
              el("p", { class: "muted", text: token.name || "" }),
            ),
            el(
              "div",
              { class: "detail-price" },
              el("strong", { text: price(token.price_usd) }),
              el("span", { class: num(token.pct_h1) >= 0 ? "pos" : "neg", text: `${num(token.pct_h1) >= 0 ? "+" : ""}${num(token.pct_h1).toFixed(2)}% · 1h` }),
            ),
            actions,
          ),
        ),
      );
      ctx.setMeta({ title: `${token.symbol || "Token"} · Details`, crumb: "Research" });
    }

    function renderStats(token) {
      const items = [
        { label: "Liquidity", value: money(token.liquidity_usd, 0), foot: "DEX pooled depth" },
        { label: "Market cap", value: token.market_cap_usd ? money(token.market_cap_usd, 0) : "—", foot: `FDV ${token.fdv_usd ? money(token.fdv_usd, 0) : "—"}` },
        { label: "1h volume", value: money(token.volume_h1, 0), foot: `5m ${money(token.volume_m5, 0)}` },
        { label: "1h activity", value: `${token.buys_h1 ?? 0} / ${token.sells_h1 ?? 0}`, foot: "buys / sells" },
        { label: "Security", value: securityBadge(token.security), foot: token.security ? `${token.security.critical_pass}/${token.security.critical_total} critical checks` : "no provider data" },
        { label: "Score", value: scoreCell(token.score), foot: `Confidence ${Math.round(num(token.data_confidence) * 100)}%` },
      ];
      mount(
        statsNode,
        el(
          "div",
          { class: "grid" },
          ...items.map((item) =>
            el(
              "div",
              { class: "col-2" },
              el(
                "div",
                { class: "stat glass edge-light" },
                el("span", { class: "stat-label", text: item.label }),
                el("div", { class: "stat-value" }, item.value),
                el("div", { class: "stat-foot", text: item.foot }),
              ),
            ),
          ),
        ),
      );
    }

    function renderChart(history) {
      const points = (history && history.points) || [];
      if (!points.length) {
        mount(chartBody, empty({ icon: "◌", title: "No snapshots yet", message: "The scanner records the first observation on its next tick." }));
        return;
      }
      duelChart(chartBody, points);
    }

    function renderMarket(token) {
      const pair = token.pair || {};
      const rows = [
        ["Pair", pair.pair_address || "—"],
        ["DEX", pair.dex_id || "—"],
        ["Quote", pair.quote_symbol || "—"],
        ["Pair created", token.pair_created_at ? `${clock(token.pair_created_at)} · ${timeAgo(token.pair_created_at)}` : "—"],
        ["First discovered", token.first_discovered_at ? `${clock(token.first_discovered_at)} · ${timeAgo(token.first_discovered_at)}` : "—"],
        ["Last snapshot", token.snapshot_ts ? `${clock(token.snapshot_ts)} · ${timeAgo(token.snapshot_ts)}` : "—"],
        ["Contract", token.address],
      ];
      mount(
        marketBody,
        el(
          "dl",
          { class: "kv" },
          ...rows.flatMap(([label, value]) => [
            el("dt", { text: label }),
            el("dd", { class: "truncate", text: String(value), title: String(value) }),
          ]),
        ),
        el(
          "div",
          { class: "row wrap", style: { gap: "6px" } },
          copyButton(token.address, "Copy address"),
          token.pair ? copyButton(token.pair.pair_address, "Copy pair") : null,
        ),
        el(
          "div",
          { class: "callout info" },
          el("span", { class: "callout-icon", text: "i" }),
          el(
            "div",
            {},
            el("strong", { text: "Paper-only instrument" }),
            el("div", { text: "Prices come from public snapshots. Nothing here can sign a transaction or touch a wallet." }),
          ),
        ),
      );
    }

    function renderScore(token) {
      const score = token.score;
      if (!score) {
        mount(scoreBody, empty({ icon: "◇", title: "Not scored yet", message: "Scoring runs after the first enriched snapshot." }));
        return;
      }
      const components = score.components || {};
      mount(
        scoreBody,
        el(
          "div",
          { class: "row wrap", style: { gap: "20px", alignItems: "center" } },
          progressRing(score.score, "/100", `Confidence ${Math.round(num(score.confidence) * 100)}%`),
          el(
            "div",
            { class: "stack", style: { gap: "6px", flex: "1", minWidth: "180px" } },
            el("div", { class: "row wrap" }, signalBadge(score.decision), badge(score.decision === "REJECT" ? "REJECT" : "HOLD", `rank ${num(score.rank_score).toFixed(1)}`)),
            el("span", { class: "muted", text: `Security risk ${num(score.security_risk).toFixed(0)}/100 · signal strength ${num(score.signal_strength).toFixed(2)}` }),
            score.rejection_codes && score.rejection_codes.length ? reasonChips(score.rejection_codes, 6) : el("span", { class: "muted", text: "No rejection codes." }),
          ),
        ),
        el(
          "div",
          { style: { marginTop: "14px" } },
          ...Object.entries(WEIGHTS).map(([key, weight]) =>
            el(
              "div",
              { class: "component" },
              el("div", { class: "c-name" }, el("strong", { text: key }), el("span", { text: `weight ${weight}` })),
              el("div", { class: "c-bar" }, el("i", { style: { width: `${Math.max(0, Math.min(100, (num(components[key]) / weight) * 100))}%` } })),
              el("div", { class: "c-value", text: `${num(components[key]).toFixed(1)} / ${weight}` }),
            ),
          ),
        ),
        el(
          "div",
          { class: "stack", style: { gap: "6px", marginTop: "12px" } },
          el("span", { class: "label", text: "Why this score" }),
          ...(score.explanations || []).map((line) => el("p", { class: "muted", style: { fontSize: "12px", lineHeight: "1.6" }, text: line })),
        ),
      );
    }

    function renderSecurity(token) {
      const security = token.security;
      if (!security) {
        mount(
          securityBody,
          callout({
            tone: "warning",
            title: "No security data",
            children: "No provider returned a verdict. The strategy blocks automatic entries rather than assuming the token is safe.",
          }),
        );
        return;
      }
      const fields = Object.values(security.fields || {}).sort(
        (a, b) => (FIELD_ORDER[a.status] ?? 9) - (FIELD_ORDER[b.status] ?? 9),
      );
      mount(
        securityBody,
        el(
          "div",
          { class: "row wrap", style: { gap: "8px", marginBottom: "10px" } },
          securityBadge(security),
          el("span", { class: "badge badge-unknown", text: `risk ${num(security.risk_score).toFixed(0)}/100` }),
          el("span", { class: "badge badge-info", text: `${security.critical_pass}/${security.critical_total} critical verified` }),
          el("span", { class: "label", text: `checked ${timeAgo(security.ts)} · ${security.provider}` }),
        ),
        el(
          "div",
          { class: "sec-list" },
          ...fields.map((fieldValue) =>
            el(
              "div",
              { class: "sec-row" },
              el("span", { class: "sec-name", text: String(fieldValue.name || "").replace(/_/g, " ") }),
              badge(fieldValue.status, fieldValue.status),
              el(
                "span",
                { class: "sec-value", title: fieldValue.reason || "" },
                `${fieldValue.value == null ? "—" : typeof fieldValue.value === "object" ? JSON.stringify(fieldValue.value) : String(fieldValue.value)}`,
              ),
              el("span", { class: "sec-provider", text: fieldValue.source || "—" }),
            ),
          ),
        ),
        security.reasons && security.reasons.length
          ? el(
              "div",
              { class: "callout warning", style: { marginTop: "12px" } },
              el("span", { class: "callout-icon", text: "!" }),
              el(
                "div",
                {},
                el("strong", { text: "Reviewer notes" }),
                ...security.reasons.map((reason) => el("div", { text: reason })),
              ),
            )
          : null,
      );
    }

    function renderDecisions(token) {
      const rows = token.decisions || [];
      mount(
        decisionsBody,
        dataTable({
          columns: [
            { label: "When", render: (row) => timeCell(row.created_at) },
            { label: "Action", align: "center", render: (row) => signalBadge(row.action) },
            { label: "Reasons", render: (row) => reasonChips(row.reason_codes, 5) },
            { label: "Metrics", render: (row) => metricsText(row.metrics) },
          ],
          rows,
          emptyState: empty({ title: "No decisions yet", message: "The strategy logs an evaluation once the observation window is satisfied." }),
        }),
      );
    }

    function renderSnapshots(history) {
      const points = ((history && history.points) || []).slice(-40).reverse();
      mount(
        dataBody,
        dataTable({
          columns: [
            { label: "Time", render: (row) => el("span", { class: "numeric", text: clock(row.ts) }) },
            { label: "Price", align: "right", render: (row) => el("span", { class: "numeric", text: price(row.price) }) },
            { label: "Liquidity", align: "right", render: (row) => usdCell(row.liquidity, 0) },
            { label: "1h volume", align: "right", render: (row) => usdCell(row.volume_h1, 0) },
            { label: "Buys / sells", align: "right", render: (row) => el("span", { class: "numeric", text: `${row.buys_h1} / ${row.sells_h1}` }) },
            { label: "5m", align: "right", render: (row) => changeCell(row.pct_m5) },
            { label: "1h", align: "right", render: (row) => changeCell(row.pct_h1) },
          ],
          rows: points,
          emptyState: empty({ title: "No snapshots", message: "Snapshots start with the next scanner tick." }),
        }),
      );
    }

    async function toggleWatch() {
      if (!state.token || state.watchBusy) return;
      state.watchBusy = true;
      const token = state.token;
      try {
        if (token.in_watchlist) {
          await api.unwatchToken(token.id);
          token.in_watchlist = false;
          toast({ title: "Removed from watchlist", message: token.symbol, type: "info" });
        } else {
          await api.watchToken(token.id);
          token.in_watchlist = true;
          toast({ title: "Added to watchlist", message: token.symbol, type: "success" });
        }
        renderHeader(token);
      } catch (error) {
        toastError(error);
      } finally {
        state.watchBusy = false;
      }
    }

    async function load() {
      try {
        const token = await api.token(id);
        if (!ctx.isActive()) return;
        state.token = token;
        renderHeader(token);
        renderStats(token);
        renderMarket(token);
        renderScore(token);
        renderSecurity(token);
        renderDecisions(token);
        loadHistory();
      } catch (error) {
        if (!ctx.isActive()) return;
        mount(
          headerNode,
          el(
            "div",
            { class: "panel glass" },
            callout({
              tone: error.code === "NOT_FOUND" ? "warning" : "danger",
              title: error.code === "NOT_FOUND" ? "Token not found" : "Could not load token",
              children: error.message,
            }),
            el("div", { class: "row" }, el("a", { class: "btn btn-sm", href: "#/scanner", text: "Back to scanner" })),
          ),
        );
        for (const node of [statsNode, chartBody, marketBody, scoreBody, securityBody, decisionsBody, dataBody]) {
          mount(node, "");
        }
      }
    }

    async function loadHistory() {
      try {
        const history = await api.tokenHistory(id, { hours: state.hours, limit: 500 });
        if (!ctx.isActive()) return;
        state.history = history;
        renderChart(history);
        renderSnapshots(history);
      } catch {
        renderChart(null);
      }
    }

    poll(ctx, REFRESH_MS, load);
    listen(ctx, ["scanner", "trade"], load);
    onGlobalRefresh(ctx, load);
    load();
    return root;
  },
};

function metricsText(metrics) {
  const entries = Object.entries(metrics || {})
    .filter(([, value]) => value != null && typeof value !== "object")
    .slice(0, 4);
  if (!entries.length) return el("span", { class: "muted", text: "—" });
  return el(
    "span",
    { class: "inline-list" },
    ...entries.map(([key, value]) =>
      el("span", { class: "badge badge-unknown", text: `${key.replace(/_/g, " ")} ${typeof value === "number" ? value.toFixed(2) : value}` }),
    ),
  );
}

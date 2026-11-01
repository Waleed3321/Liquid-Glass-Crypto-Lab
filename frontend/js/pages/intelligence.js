/* Market intelligence: distribution, rejection reasons and ranked opportunities. */

import { api } from "../api.js";
import { callout, el, loadingRows, panel, statTile } from "../ui.js";
import { humanizeCode, int, money, num } from "../format.js";
import { barChart, donutChart } from "../charts.js";
import {
  chainCell,
  changeCell,
  listen,
  onGlobalRefresh,
  poll,
  reasonChips,
  REFRESH_MS,
  scoreCell,
  securityBadge,
  signalBadge,
  tokenIdentity,
} from "./shared.js";

function distRows(entries, { max, color = "" } = {}) {
  if (!entries.length) return el("p", { class: "muted", text: "No data in the six-hour window yet." });
  const ceiling = max || Math.max(...entries.map(([, value]) => num(value)), 1);
  return el(
    "div",
    { class: "dist" },
    ...entries.map(([label, value]) =>
      el(
        "div",
        { class: "dist-row" },
        el("span", { text: humanizeCode(label) }),
        el("div", { class: "dist-bar" }, el("i", { style: { width: `${Math.max(2, (num(value) / ceiling) * 100)}%`, background: color || undefined } })),
        el("span", { class: "dist-value", text: String(value) }),
      ),
    ),
  );
}

export default {
  title: "Market Intelligence",
  crumb: "Research",
  async render(ctx) {
    const page = el("div", { class: "stack" });
    const head = el(
      "div",
      { class: "page-head" },
      el(
        "div",
        {},
        el("span", { class: "label", text: "Research" }),
        el("h2", { text: "Market intelligence" }),
        el("p", {
          class: "muted",
          text: "A read-only view of the six-hour discovery window: score distribution, security outcomes, rejection reasons and the strongest candidates.",
        }),
      ),
      el("div", { class: "page-actions" }, el("span", { class: "badge badge-info", text: "6h window" })),
    );

    const tiles = el("div", { class: "grid" });
    const charts = el("div", { class: "grid" });
    const dists = el("div", { class: "grid" });
    const topHost = el("div", {});
    const rejectedHost = el("div", {});
    page.append(head, tiles, charts, dists, topHost, rejectedHost);

    const renderTiles = (market) => {
      tiles.replaceChildren(
        ...[
          { label: "Tokens tracked", value: int(market.tokens_tracked), foot: `discovered in the last 6h` },
          { label: "New last hour", value: int(market.discovered_last_hour), foot: "first-seen within 60m" },
          { label: "Average score", value: num(market.avg_score).toFixed(1), foot: "across the window" },
          { label: "Watchlist", value: int(market.watchlist_count), foot: `${int(market.open_positions)} in paper positions` },
        ].map((item) =>
          el("div", { class: "col-3" }, statTile({ label: item.label, value: item.value, foot: el("span", { class: "muted", text: item.foot }) })),
        ),
      );
    };

    const renderCharts = (market) => {
      const bucketNode = el("div", { class: "chart short" });
      const chainNode = el("div", { class: "chart short" });
      charts.replaceChildren(
        el("div", { class: "col-7" }, panel({
          title: "Score distribution",
          subtitle: "Every discovered token lands in one bucket, including rejects.",
          body: bucketNode,
        })),
        el("div", { class: "col-5" }, panel({
          title: "Chain split",
          subtitle: "Solana and BNB Chain discovery volume.",
          body: chainNode,
        })),
      );
      const buckets = market.score_buckets || {};
      barChart(bucketNode, Object.keys(buckets), Object.values(buckets), { suffix: " tokens" });
      const chains = market.by_chain || {};
      donutChart(
        chainNode,
        [
          { label: "Solana", value: chains.solana || 0, color: "#a78bfa" },
          { label: "BNB Chain", value: chains.bsc || 0, color: "#ffc65c" },
        ],
        { centerLabel: "TOKENS", centerValue: int(market.tokens_tracked) },
      );
    };

    const renderDists = (market) => {
      const security = market.security || {};
      const securityEntries = ["PASS", "WARNING", "FAIL", "UNKNOWN", "UNAVAILABLE"].map((key) => [key, security[key] || 0]);
      const codes = Object.entries(market.rejection_codes || {});
      const decisions = Object.entries(market.decisions_24h || {});
      dists.replaceChildren(
        el("div", { class: "col-4" }, panel({
          title: "Security outcomes",
          subtitle: "Missing data is never treated as safe.",
          body: distRows(securityEntries, { color: "rgba(49, 224, 160, 0.65)" }),
        })),
        el("div", { class: "col-4" }, panel({
          title: "Top rejection reasons",
          subtitle: "Why the engine refused a candidate.",
          body: distRows(codes, { color: "rgba(255, 92, 122, 0.6)" }),
        })),
        el("div", { class: "col-4" }, panel({
          title: "Decisions (24h)",
          subtitle: "Enter, hold, reject and exit counts.",
          body: distRows(decisions, { color: "rgba(111, 168, 255, 0.6)" }),
        })),
      );
    };

    const renderTop = (market) => {
      const rows = market.top_opportunities || [];
      const body = rows.length
        ? el(
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
                  el("th", { class: "right", scope: "col", text: "Score" }),
                  el("th", { class: "right", scope: "col", text: "Liquidity" }),
                  el("th", { class: "right", scope: "col", text: "1h" }),
                  el("th", { scope: "col", text: "Security" }),
                  el("th", { scope: "col", text: "Signal" }),
                ),
              ),
              el(
                "tbody",
                {},
                ...rows.map((row) =>
                  el(
                    "tr",
                    {},
                    el("td", {}, tokenIdentity(row)),
                    el("td", {}, chainCell(row.chain)),
                    el("td", { class: "right" }, scoreCell({ score: row.score, confidence: row.confidence })),
                    el("td", { class: "right numeric", text: money(row.liquidity_usd) }),
                    el("td", { class: "right" }, changeCell(row.pct_h1)),
                    el("td", {}, securityBadge(row.security ? { overall: row.security } : null)),
                    el("td", {}, signalBadge(row.signal)),
                  ),
                ),
              ),
            ),
          )
        : el("div", { class: "empty" }, el("div", { class: "empty-icon", text: "◇" }), el("p", { class: "muted", text: "No scored candidates in the window yet." }));

      topHost.replaceChildren(
        panel({
          title: "Top opportunities",
          subtitle: "Ranked by opportunity score inside the six-hour discovery window.",
          body,
        }),
      );
    };

    const renderRejected = (market) => {
      const rows = market.recent_rejected || [];
      const body = rows.length
        ? el(
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
                  el("th", { class: "right", scope: "col", text: "Score" }),
                  el("th", { scope: "col", text: "Security" }),
                  el("th", { scope: "col", text: "Reasons" }),
                ),
              ),
              el(
                "tbody",
                {},
                ...rows.map((row) =>
                  el(
                    "tr",
                    {},
                    el("td", {}, tokenIdentity(row, { sub: false })),
                    el("td", {}, chainCell(row.chain)),
                    el("td", { class: "right numeric", text: num(row.score).toFixed(1) }),
                    el("td", {}, securityBadge(row.security ? { overall: row.security } : null)),
                    el("td", {}, reasonChips(row.reason_codes || [])),
                  ),
                ),
              ),
            ),
          )
        : el("div", { class: "empty" }, el("div", { class: "empty-icon", text: "◇" }), el("p", { class: "muted", text: "No rejected candidates recorded in this window." }));

      rejectedHost.replaceChildren(
        panel({
          title: "Recently rejected",
          subtitle: "Rejections are stored with their reason codes so nothing is hidden.",
          body,
        }),
      );
    };

    async function refresh() {
      try {
        const market = await api.marketAnalytics();
        if (!ctx.isActive()) return;
        renderTiles(market);
        renderCharts(market);
        renderDists(market);
        renderTop(market);
        renderRejected(market);
      } catch (error) {
        if (error.name === "AbortError" || !ctx.isActive()) return;
        tiles.replaceChildren(el("div", { class: "col-12" }, callout({ tone: "danger", title: "Analytics unavailable", children: error.message })));
      }
    }

    tiles.replaceChildren(el("div", { class: "col-12" }, loadingRows(1)));
    await refresh();
    poll(ctx, REFRESH_MS * 2, refresh);
    listen(ctx, ["scanner", "trade"], refresh);
    onGlobalRefresh(ctx, refresh);

    return page;
  },
};

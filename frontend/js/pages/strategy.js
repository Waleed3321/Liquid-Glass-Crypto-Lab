/* Strategy Lab: Strategy A configuration, gate documentation and decision log. */

import { api } from "../api.js";
import { confirmDialog, badge, callout, el, input, panel, toast, toastError } from "../ui.js";
import { int, money, num, timeAgo } from "../format.js";
import { listen, onGlobalRefresh, poll, reasonChips } from "./shared.js";

const GROUPS = [
  {
    id: "observation",
    title: "Observation window",
    note: "A token cannot be bought until the scanner has watched it for long enough with dense snapshots.",
    fields: [
      { key: "min_observation_minutes", label: "Minimum observation", unit: "minutes", step: "1", min: "1", max: "120" },
      { key: "min_snapshots", label: "Minimum snapshots", unit: "points", step: "1", min: "3", max: "120" },
      { key: "max_snapshot_gap_seconds", label: "Max snapshot gap", unit: "seconds", step: "10", min: "60", max: "900" },
    ],
  },
  {
    id: "quality",
    title: "Entry quality",
    note: "Score, confidence and signal strength must all clear their thresholds before an entry is considered.",
    fields: [
      { key: "entry_score_threshold", label: "Score threshold", unit: "of 100", step: "1", min: "0", max: "100" },
      { key: "entry_confidence_threshold", label: "Confidence threshold", unit: "0–1", step: "0.05", min: "0", max: "1" },
      { key: "min_signal_strength", label: "Signal strength", unit: "0–1", step: "0.05", min: "0", max: "1" },
    ],
  },
  {
    id: "trend",
    title: "Trend, pullback & anti-vertical guard",
    note: "Buys a controlled pullback inside an established hour trend. Vertical candles are always refused.",
    fields: [
      { key: "trend_min_pct_h1", label: "Trend floor (1h)", unit: "%", step: "0.5", min: "0", max: "50" },
      { key: "trend_max_pct_h1", label: "Trend ceiling (1h)", unit: "%", step: "1", min: "1", max: "200" },
      { key: "pullback_min_pct", label: "Pullback floor", unit: "% off peak", step: "0.5", min: "0.5", max: "30" },
      { key: "pullback_max_pct", label: "Pullback ceiling", unit: "% off peak", step: "0.5", min: "1", max: "50" },
      { key: "stabilization_band_pct", label: "Stabilisation band", unit: "%", step: "0.5", min: "0.5", max: "15" },
      { key: "max_pct_m5", label: "Max 5m move", unit: "%", step: "1", min: "1", max: "100" },
      { key: "sma_window", label: "SMA window", unit: "snapshots", step: "1", min: "3", max: "60" },
      { key: "max_price_vs_sma_pct", label: "Max price vs SMA", unit: "%", step: "1", min: "1", max: "100" },
    ],
  },
  {
    id: "liquidity",
    title: "Liquidity & activity",
    note: "Thin pools and fading volume are excluded; the buy/sell ratio must stay in a healthy band.",
    fields: [
      { key: "min_liquidity_usd", label: "Liquidity floor", unit: "USD", step: "500", min: "1000", max: "5000000" },
      { key: "liquidity_deterioration_pct", label: "Max liquidity drop", unit: "%", step: "1", min: "5", max: "90" },
      { key: "min_turnover_h1", label: "Min hourly turnover", unit: "ratio", step: "0.05", min: "0", max: "10" },
      { key: "min_buy_sell_ratio", label: "Min buy/sell ratio", unit: "ratio", step: "0.1", min: "0.1", max: "10" },
      { key: "max_buy_sell_ratio", label: "Max buy/sell ratio", unit: "ratio", step: "0.1", min: "1", max: "20" },
    ],
  },
  {
    id: "risk",
    title: "Sizing & hard caps",
    note: "Hard caps are enforced server-side. Lowering them is allowed; never raising them past the specification.",
    fields: [
      { key: "min_position_usd", label: "Minimum position", unit: "USD", step: "0.1", min: "0.1", max: "10" },
      { key: "max_position_usd", label: "Position cap", unit: "USD ≤ 2.50", step: "0.1", min: "0.1", max: "2.5" },
      { key: "max_open_positions", label: "Open position cap", unit: "≤ 3", step: "1", min: "1", max: "3" },
      { key: "daily_loss_limit_usd", label: "Daily loss cap", unit: "USD ≤ 0.50", step: "0.05", min: "0.05", max: "0.5" },
      { key: "max_price_impact_pct", label: "Impact cap", unit: "% ≤ 1.00", step: "0.1", min: "0.1", max: "1" },
      { key: "max_price_age_seconds", label: "Max snapshot age", unit: "seconds", step: "10", min: "10", max: "3600" },
    ],
    hardCaps: true,
  },
  {
    id: "exits",
    title: "Exit rules",
    note: "Stops are checked every tick before any new entry. Take-profit exits use stable idempotency keys.",
    fields: [
      { key: "stop_loss_pct", label: "Stop loss", unit: "%", step: "1", min: "1", max: "90" },
      { key: "trail_stop_pct", label: "Trailing stop", unit: "%", step: "1", min: "1", max: "50" },
      { key: "protect_after_profit_pct", label: "Arm protection at", unit: "% profit", step: "1", min: "5", max: "100" },
      { key: "take_profit_half_pct", label: "Take half at", unit: "% profit", step: "5", min: "10", max: "200" },
      { key: "take_profit_full_pct", label: "Close at", unit: "% profit", step: "5", min: "20", max: "500" },
      { key: "momentum_breakdown_pct_m5", label: "Momentum breakdown", unit: "% 5m drop", step: "1", min: "1", max: "50" },
      { key: "liquidity_collapse_pct", label: "Liquidity collapse", unit: "% of entry", step: "1", min: "10", max: "95" },
    ],
  },
  {
    id: "costs",
    title: "Costs & cooldown",
    note: "Round trips that cost more than the ceiling are skipped, and a token cannot be re-entered immediately after an exit.",
    fields: [
      { key: "max_roundtrip_cost_pct", label: "Max round-trip cost", unit: "%", step: "0.1", min: "0.1", max: "20" },
      { key: "cooldown_after_exit_minutes", label: "Cooldown after exit", unit: "minutes", step: "1", min: "1", max: "720" },
    ],
  },
];

function actionBadge(action) {
  const value = String(action || "HOLD").toUpperCase();
  return badge(value === "ENTER" ? "ENTER" : value === "EXIT" ? "EXIT" : value === "REJECT" ? "REJECT" : "HOLD", value);
}

export default {
  title: "Strategy Lab",
  crumb: "Research",
  async render(ctx) {
    const page = el("div", { class: "stack" });
    const resetBtn = el("button", { class: "btn btn-sm", type: "button", text: "Reset defaults" });
    const saveBtn = el("button", { class: "btn btn-primary btn-sm", type: "button", text: "Save configuration" });
    const head = el(
      "div",
      { class: "page-head" },
      el(
        "div",
        {},
        el("span", { class: "label", text: "Research" }),
        el("h2", { text: "Strategy A · Conservative Momentum Pullback" }),
        el("p", {
          class: "muted",
          text: "A paper-only setup engine: wait ten minutes, require a real uptrend, buy a stabilised pullback, refuse vertical candles and unsafe tokens. Nothing is forced.",
        }),
      ),
      el("div", { class: "page-actions" }, resetBtn, saveBtn),
    );
    const statusLine = el("div", { class: "row wrap" });
    const metaPanel = el("div", { class: "panel glass" });
    const formHost = el("div", { class: "stack" });
    const decisionsHost = el("div", { class: "panel glass" });
    page.append(head, statusLine, metaPanel, formHost, decisionsHost);

    const inputs = new Map();
    let config = null;
    let dirty = false;

    const markDirty = () => {
      dirty = true;
      statusLine.replaceChildren(
        el("span", { class: "badge badge-warning", text: "Unsaved changes" }),
        el("span", { class: "muted", text: "The scanner keeps using the last saved configuration until you save." }),
      );
    };

    const buildForm = () => {
      formHost.replaceChildren(
        el(
          "div",
          { class: "grid" },
          ...GROUPS.map((group) =>
            el(
              "div",
              { class: group.id === "trend" || group.id === "exits" ? "col-12" : "col-6" },
              panel({
                title: group.title,
                subtitle: group.note,
                actions: group.hardCaps ? badge("WARNING", "Hard caps") : null,
                body: el(
                  "div",
                  { class: "config-grid" },
                  ...group.fields.map((spec) => {
                    const control = input({
                      type: "number",
                      step: spec.step,
                      min: spec.min,
                      max: spec.max,
                      value: String(num(config?.settings?.[spec.key])),
                      "aria-label": spec.label,
                    });
                    control.addEventListener("input", markDirty);
                    inputs.set(spec.key, { control, spec });
                    return el(
                      "div",
                      { class: "config-item" },
                      el(
                        "div",
                        { class: "cfg-label" },
                        el("span", { text: spec.label }),
                        el("span", { class: "cfg-unit", text: spec.unit }),
                      ),
                      control,
                    );
                  }),
                ),
              }),
            ),
          ),
        ),
      );
      inputs.forEach(({ control, spec }, key) => {
        control.value = String(num(config?.settings?.[key]));
        control.min = spec.min;
        control.max = spec.max;
      });
    };

    const renderMeta = () => {
      const strategy = config?.strategy || {};
      metaPanel.replaceChildren(
        el(
          "div",
          { class: "panel-head" },
          el(
            "div",
            { class: "panel-title" },
            el("h3", { text: `${strategy.name || "Strategy A"} · ${config?.strategy_version || "A-1.0"}` }),
            el("p", { text: strategy.summary || "" }),
          ),
          el(
            "div",
            { class: "row wrap" },
            badge("PASS", "Paper only"),
            el("span", { class: "badge badge-info", text: "Version " + (config?.strategy_version || "—") }),
          ),
        ),
        el(
          "div",
          { class: "split-2" },
          el(
            "div",
            {},
            el("span", { class: "label-brutal", text: "Entry gates" }),
            el(
              "div",
              { class: "rule-list", style: { marginTop: "10px" } },
              ...(strategy.entry_gates || []).map((rule) => el("div", { class: "rule", text: rule })),
            ),
          ),
          el(
            "div",
            {},
            el("span", { class: "label-brutal", text: "Exit rules" }),
            el(
              "div",
              { class: "rule-list", style: { marginTop: "10px" } },
              ...(strategy.exit_rules || []).map((rule) => el("div", { class: "rule", text: rule })),
            ),
          ),
        ),
        el(
          "div",
          { class: "callout info" },
          el("span", { class: "callout-icon", text: "i" }),
          el(
            "div",
            {},
            el("strong", { text: "Hard caps" }),
            el(
              "div",
              {
                text:
                  "Starting balance $10.00 · max 3 open positions · max $2.50 per entry · $0.50 daily loss · 1.00% price impact. The backend rejects anything beyond these regardless of this form.",
              },
            ),
          ),
        ),
      );
    };

    const renderStatus = () => {
      const settings = config?.settings || {};
      statusLine.replaceChildren(
        el("span", { class: "badge badge-pass", text: "Loaded" }),
        el("span", { class: "muted", text: `Score ≥ ${num(settings.entry_score_threshold).toFixed(0)} · confidence ≥ ${num(settings.entry_confidence_threshold).toFixed(2)} · stop ${num(settings.stop_loss_pct).toFixed(0)}% · trail ${num(settings.trail_stop_pct).toFixed(0)}%` }),
        el("span", { class: "muted", text: `max ${money(settings.max_position_usd)} per entry · ${int(settings.max_open_positions)} slots · ${money(settings.daily_loss_limit_usd)} daily loss cap` }),
      );
    };

    const decisionRows = (decisions) => {
      if (!decisions.length) {
        return el("div", { class: "empty" }, el("div", { class: "empty-icon", text: "◇" }), el("p", { class: "muted", text: "No strategy decisions recorded yet. They appear after each scanner tick." }));
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
              el("th", { scope: "col", text: "When" }),
              el("th", { scope: "col", text: "Token" }),
              el("th", { scope: "col", text: "Action" }),
              el("th", { scope: "col", text: "Reasons" }),
              el("th", { scope: "col", text: "Note" }),
            ),
          ),
          el(
            "tbody",
            {},
            ...decisions.map((decision) =>
              el(
                "tr",
                {},
                el("td", {}, el("span", { class: "numeric", text: timeAgo(decision.created_at), title: decision.created_at || "" })),
                el(
                  "td",
                  {},
                  el("a", { href: `#/token/${decision.token_id}`, class: "numeric", text: `#${decision.token_id}` }),
                ),
                el("td", {}, actionBadge(decision.action)),
                el("td", {}, reasonChips(decision.reason_codes || [], 3)),
                el("td", { class: "muted truncate", text: decision.note || "—" }),
              ),
            ),
          ),
        ),
      );
    };

    const renderDecisions = (decisions) => {
      decisionsHost.replaceChildren(
        el(
          "div",
          { class: "panel-head" },
          el(
            "div",
            { class: "panel-title" },
            el("h3", { text: "Decision log" }),
            el("p", { text: "Every evaluated candidate stores its verdict and the exact reasons — including rejections." }),
          ),
          el("span", { class: "result-count", text: `${decisions.length} recent` }),
        ),
        decisionRows(decisions),
      );
    };

    const collect = () => {
      const out = {};
      inputs.forEach(({ control }, key) => {
        out[key] = num(control.value);
      });
      return out;
    };

    const save = async () => {
      saveBtn.disabled = true;
      try {
        const payload = await api.saveStrategy(collect());
        config = payload;
        dirty = false;
        renderStatus();
        renderMeta();
        buildForm();
        toast({ title: "Strategy saved", message: "The scanner picks up the new configuration on its next tick.", type: "success" });
      } catch (error) {
        toastError(error);
      } finally {
        saveBtn.disabled = false;
      }
    };

    const reset = async () => {
      const ok = await confirmDialog({
        title: "Reset Strategy A?",
        message: "Every override returns to the documented defaults. Hard caps stay enforced either way.",
        confirmLabel: "Reset to defaults",
        danger: true,
      });
      if (!ok) return;
      try {
        config = await api.resetStrategy();
        dirty = false;
        renderStatus();
        renderMeta();
        buildForm();
        toast({ title: "Defaults restored", message: "Strategy A is back to its shipped configuration.", type: "success" });
      } catch (error) {
        toastError(error);
      }
    };

    saveBtn.addEventListener("click", save);
    resetBtn.addEventListener("click", reset);

    const loadDecisions = async () => {
      try {
        const payload = await api.decisions(50);
        if (!ctx.isActive()) return;
        renderDecisions(payload.decisions || []);
      } catch {
        /* the log is secondary to the configuration */
      }
    };

    try {
      config = await api.strategy(50);
      if (!ctx.isActive()) return;
      renderStatus();
      renderMeta();
      buildForm();
      renderDecisions(config.decisions || []);
    } catch (error) {
      formHost.replaceChildren(callout({ tone: "danger", title: "Strategy unavailable", children: (error && error.message) || "Could not load the configuration." }));
    }

    poll(ctx, 60000, loadDecisions);
    listen(ctx, ["scanner", "trade"], loadDecisions);
    onGlobalRefresh(ctx, loadDecisions);

    return page;
  },
};

/* Settings: scanner, strategy summary, notifications, access, integrations. */

import { api, getAdminToken, setAdminToken } from "../api.js";
import { badge, callout, el, field, input, loadingRows, panel, switchControl, toast, toastError } from "../ui.js";
import { humanizeCode, int, money, num, pct } from "../format.js";

function kvRow(label, value) {
  return [el("dt", { text: label }), el("dd", {}, value instanceof Node ? value : String(value ?? "—"))];
}

function providerChips(providers) {
  const host = el("div", { class: "inline-list" });
  Object.entries(providers || {}).forEach(([name, health]) => {
    if (name === "cache" || name === "discord" || !health || typeof health !== "object") return;
    const failing = health.circuit_open || num(health.consecutive_failures) > 0;
    const node = el(
      "span",
      {
        class: `chip ${failing ? "badge-warning" : ""}`.trim(),
        title: `${num(health.requests)} requests · failures ${num(health.consecutive_failures)} · ${health.last_error || "no recent error"}`,
      },
      el("span", { class: `badge badge-${health.circuit_open ? "fail" : failing ? "warning" : "pass"}`, text: health.circuit_open ? "BREAKER" : failing ? "DEGRADED" : "OK" }),
      el("span", { text: humanizeCode(name) }),
    );
    host.append(node);
  });
  return host;
}

export default {
  title: "Settings",
  crumb: "Research",
  async render(ctx) {
    const page = el("div", { class: "stack" });
    const reloadBtn = el("button", { class: "btn btn-sm", type: "button", text: "Reload" });
    const head = el(
      "div",
      { class: "page-head" },
      el(
        "div",
        {},
        el("span", { class: "label", text: "Research" }),
        el("h2", { text: "Settings" }),
        el("p", {
          class: "muted",
          text: "Scanner cadence, alert preferences, admin access and integration health. Hard risk caps stay fixed regardless of what is saved here.",
        }),
      ),
      el("div", { class: "page-actions" }, reloadBtn),
    );

    const host = el("div", { class: "stack" }, loadingRows(3));
    page.append(head, host);

    let data = null;
    let adminToken = getAdminToken();

    const savePartial = async (body, successMessage) => {
      try {
        data = await api.saveSettings(body);
        toast({ title: "Saved", message: successMessage, type: "success" });
        render();
      } catch (error) {
        toastError(error);
      }
    };

    const renderScanner = () => {
      const scanner = data.scanner || {};
      const runtime = data.scanner_runtime || {};
      const enabled = switchControl({
        label: "Scanner loop enabled",
        checked: Boolean(scanner.enabled),
        onChange: (value) => {
          scanner.enabled = value;
        },
      });
      const interval = input({
        type: "number",
        min: "30",
        max: "300",
        step: "5",
        value: String(num(scanner.interval_seconds)),
        "aria-label": "Scan interval in seconds",
      });
      const windowHours = input({
        type: "number",
        min: "1",
        max: "24",
        step: "1",
        value: String(num(scanner.discovery_window_hours)),
        "aria-label": "Discovery window in hours",
      });
      const saveBtn = el("button", {
        class: "btn btn-primary btn-sm",
        type: "button",
        text: "Save scanner",
        onClick: async () => {
          saveBtn.disabled = true;
          await savePartial(
            {
              scanner: {
                enabled: scanner.enabled,
                interval_seconds: num(interval.value),
                discovery_window_hours: num(windowHours.value),
              },
            },
            "The loop uses the new cadence on its next sleep cycle.",
          );
          saveBtn.disabled = false;
        },
      });

      return panel({
        title: "Scanner",
        subtitle: "The internal loop and the external cron share one guarded tick.",
        actions: badge(runtime.running ? "PASS" : "WARNING", runtime.running ? "Loop running" : "Loop idle"),
        body: el(
          "div",
          { class: "stack" },
          el(
            "div",
            { class: "config-grid" },
            el("div", { class: "config-item" }, enabled),
            el("div", { class: "config-item" }, field({ label: "Interval", control: interval, hint: "Seconds between ticks (30–300)" })),
            el("div", { class: "config-item" }, field({ label: "Discovery window", control: windowHours, hint: "Hours since pair creation (1–24)" })),
          ),
          el(
            "div",
            { class: "row-between" },
            el("span", { class: "muted", text: `Runtime interval ${int(runtime.interval_seconds)}s · enabled ${runtime.enabled ? "yes" : "no"}` }),
            saveBtn,
          ),
        ),
      });
    };

    const renderStrategy = () => {
      const strategy = data.strategy || {};
      return panel({
        title: "Strategy A",
        subtitle: "Full tuning lives in Strategy Lab; this is the active summary.",
        actions: el("a", { class: "btn btn-sm", href: "#/strategy", text: "Open Strategy Lab" }),
        body: el(
          "dl",
          { class: "kv" },
          ...kvRow("Observation", `${num(strategy.min_observation_minutes)} min · ${int(strategy.min_snapshots)} snapshots`),
          ...kvRow("Score / confidence", `${num(strategy.entry_score_threshold)} / ${num(strategy.entry_confidence_threshold).toFixed(2)}`),
          ...kvRow("Position size", `${money(strategy.min_position_usd)} – ${money(strategy.max_position_usd)}`),
          ...kvRow("Open positions", `${int(strategy.max_open_positions)} max`),
          ...kvRow("Daily loss", money(strategy.daily_loss_limit_usd)),
          ...kvRow("Impact cap", pct(strategy.max_price_impact_pct)),
          ...kvRow("Stop / trail", `${pct(strategy.stop_loss_pct)} / ${pct(strategy.trail_stop_pct)}`),
          ...kvRow("Take profit", `${pct(strategy.take_profit_half_pct)} half · ${pct(strategy.take_profit_full_pct)} full`),
        ),
      });
    };

    const renderNotifications = () => {
      const config = data.notifications || {};
      const minScore = input({
        type: "number",
        min: "0",
        max: "100",
        step: "1",
        value: String(num(config.min_score_for_alert)),
        "aria-label": "Minimum score for alerts",
      });
      const switches = {
        enabled: config.enabled,
        notify_security_warnings: config.notify_security_warnings,
        notify_entries: config.notify_entries,
        notify_exits: config.notify_exits,
      };
      const node = (label, key) =>
        switchControl({ label, checked: Boolean(config[key]), onChange: (value) => (switches[key] = value) });
      const enabled = node("Notifications enabled", "enabled");
      const entries = node("Entries", "notify_entries");
      const exits = node("Exits", "notify_exits");
      const warnings = node("Security warnings", "notify_security_warnings");
      const saveBtn = el("button", {
        class: "btn btn-primary btn-sm",
        type: "button",
        text: "Save alerts",
        onClick: async () => {
          saveBtn.disabled = true;
          await savePartial(
            {
              notifications: {
                enabled: switches.enabled,
                min_score_for_alert: num(minScore.value),
                notify_entries: switches.notify_entries,
                notify_exits: switches.notify_exits,
                notify_security_warnings: switches.notify_security_warnings,
              },
            },
            "Alert routing updated.",
          );
          saveBtn.disabled = false;
        },
      });
      return panel({
        title: "Notifications",
        subtitle: "Discord delivery state and per-event routing.",
        actions: el("a", { class: "btn btn-sm", href: "#/notifications", text: "Open log" }),
        body: el(
          "div",
          { class: "stack" },
          el(
            "div",
            { class: "config-grid" },
            el("div", { class: "config-item" }, field({ label: "Minimum score", control: minScore, hint: "A token must score at least this to alert" })),
            el("div", { class: "config-item" }, enabled),
            el("div", { class: "config-item" }, entries),
            el("div", { class: "config-item" }, exits),
            el("div", { class: "config-item" }, warnings),
          ),
          el("div", { class: "row-between" }, el("span", { class: "muted", text: "Secrets are never shown here — only whether transport is configured." }), saveBtn),
        ),
      });
    };

    const renderAccess = () => {
      const integrations = data.integrations || {};
      const tokenInput = input({
        type: "password",
        autocomplete: "off",
        placeholder: adminToken ? "token loaded for this tab" : "paste the admin token",
        "aria-label": "Admin token",
      });
      const applyBtn = el("button", {
        class: "btn btn-sm",
        type: "button",
        text: "Use token for this tab",
        onClick: () => {
          adminToken = tokenInput.value.trim();
          setAdminToken(adminToken);
          tokenInput.value = "";
          tokenInput.placeholder = adminToken ? "token loaded for this tab" : "paste the admin token";
          toast({
            title: adminToken ? "Admin token loaded" : "Admin token cleared",
            message: adminToken ? "Stored in sessionStorage only; every request now sends X-Admin-Token." : "Mutating requests will use the open lab mode.",
            type: adminToken ? "success" : "info",
          });
        },
      });
      const clearBtn = el("button", {
        class: "btn btn-sm btn-ghost",
        type: "button",
        text: "Forget",
        onClick: () => {
          adminToken = "";
          setAdminToken("");
          tokenInput.value = "";
          tokenInput.placeholder = "paste the admin token";
          toast({ title: "Admin token cleared", message: "This tab no longer sends the header.", type: "info" });
        },
      });
      return panel({
        title: "Access",
        subtitle: "Only needed when the deployment sets ADMIN_TOKEN.",
        actions: integrations.admin_token_set ? badge("WARNING", "Token required") : badge("PASS", "Open lab"),
        body: el(
          "div",
          { class: "stack" },
          integrations.admin_token_set
            ? callout({
                tone: "warning",
                title: "Mutating routes are protected",
                children: "Saving settings, starting the scanner and manual test notifications need the admin token. It is kept in this browser tab only and never written to the repository.",
              })
            : callout({
                tone: "info",
                title: "No admin token configured",
                children: "Mutating routes are open because this is a paper-only lab. Add ADMIN_TOKEN to the deployment to lock them.",
              }),
          field({ label: "Admin token", control: tokenInput, hint: "Sent as X-Admin-Token. Not persisted outside sessionStorage." }),
          el("div", { class: "row" }, applyBtn, clearBtn),
        ),
      });
    };

    const renderIntegrations = () => {
      const integrations = data.integrations || {};
      const discord = integrations.discord || {};
      const providers = integrations.providers || {};
      const cache = providers.cache || {};
      return panel({
        title: "Integrations",
        subtitle: "Keyless market data, security providers and Discord delivery.",
        actions: discord.configured ? badge("PASS", "Discord ready") : badge("WARNING", "Discord off"),
        body: el(
          "div",
          { class: "stack" },
          el(
            "dl",
            { class: "kv" },
            ...kvRow("Discord mode", humanizeCode(discord.mode || "disabled")),
            ...kvRow("Webhook", discord.webhook_set ? `set · ends ${discord.webhook_fingerprint}` : "not set"),
            ...kvRow("Bot channel", discord.bot_set ? `${discord.channel_id}` : "not set"),
            ...kvRow("Scanner tick token", integrations.scanner_tick_token_set ? "set" : "not set"),
            ...kvRow("Admin token", integrations.admin_token_set ? "set" : "not set"),
            ...kvRow("Cache", `${int(cache.entries)} entries · ${int(cache.hits)} hits · ${int(cache.misses)} misses`),
          ),
          el("span", { class: "label-brutal", text: "Provider health" }),
          providerChips(providers),
        ),
      });
    };

    const renderEnvironment = () => {
      const env = data.environment || {};
      return panel({
        title: "Environment",
        subtitle: "Read-only runtime facts. Nobody can trade real funds from this deployment.",
        body: el(
          "div",
          { class: "stack" },
          el(
            "dl",
            { class: "kv" },
            ...kvRow("App", `${env.app_env || "—"} · v${env.version || "—"}`),
            ...kvRow("Database", env.database_backend || "—"),
            ...kvRow("Paper only", env.paper_only ? "yes" : "no"),
            ...kvRow("Discovery window", `${num(env.discovery_window_hours)} hours`),
            ...kvRow("Scan interval", `${int(env.scan_interval_seconds)} seconds`),
            ...kvRow("Snapshot retention", `${int(env.retention_days)} days full resolution`),
          ),
          el(
            "dl",
            { class: "kv" },
            ...kvRow("Starting balance", `${money((data.limits || {}).initial_balance_usd)} hard-capped`),
            ...kvRow("Max open positions", int((data.limits || {}).max_open_positions)),
            ...kvRow("Max entry", money((data.limits || {}).max_position_usd)),
            ...kvRow("Daily loss", money((data.limits || {}).daily_loss_limit_usd)),
            ...kvRow("Price impact", pct((data.limits || {}).max_price_impact_pct)),
          ),
          callout({
            tone: "success",
            title: "Simulation guarantee",
            children: "No wallet, private key, signature, deposit or swap exists anywhere in this code path.",
          }),
        ),
      });
    };

    const render = () => {
      host.replaceChildren(
        el(
          "div",
          { class: "grid" },
          el("div", { class: "col-6" }, renderScanner()),
          el("div", { class: "col-6" }, renderStrategy()),
          el("div", { class: "col-6" }, renderNotifications()),
          el("div", { class: "col-6" }, renderAccess()),
          el("div", { class: "col-7" }, renderIntegrations()),
          el("div", { class: "col-5" }, renderEnvironment()),
        ),
      );
    };

    async function load() {
      try {
        data = await api.settings();
        if (!ctx.isActive()) return;
        render();
      } catch (error) {
        if (error.name === "AbortError" || !ctx.isActive()) return;
        host.replaceChildren(callout({ tone: "danger", title: "Settings unavailable", children: error.message }));
      }
    }

    reloadBtn.addEventListener("click", load);
    await load();

    return page;
  },
};

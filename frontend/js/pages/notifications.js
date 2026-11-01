/* Notifications: Discord transport, alert preferences, outbox log and tests. */

import { api } from "../api.js";
import { badge, callout, el, field, input, loadingRows, switchControl, toast, toastError } from "../ui.js";
import { humanizeCode, int, num, timeAgo } from "../format.js";
import { listen, onGlobalRefresh, poll, REFRESH_MS } from "./shared.js";

const SEVERITIES = {
  critical: "critical",
  warning: "warning",
  success: "success",
  info: "info",
};

function severityKey(severity) {
  return String(severity || "INFO").toLowerCase();
}

function statusBadge(status) {
  const value = String(status || "PENDING").toUpperCase();
  return badge(value, value.replace(/_/g, " "));
}

export default {
  title: "Notifications",
  crumb: "Research",
  async render(ctx) {
    const page = el("div", { class: "stack" });
    const dispatchBtn = el("button", { class: "btn btn-sm", type: "button", text: "Dispatch queue" });
    const testBtn = el("button", { class: "btn btn-primary btn-sm", type: "button", text: "Send test" });
    const head = el(
      "div",
      { class: "page-head" },
      el(
        "div",
        {},
        el("span", { class: "label", text: "Research" }),
        el("h2", { text: "Notifications" }),
        el("p", {
          class: "muted",
          text: "Entry, exit and security alerts are queued in the database and delivered to Discord from an outbox — a Discord outage never blocks a paper trade.",
        }),
      ),
      el("div", { class: "page-actions" }, dispatchBtn, testBtn),
    );

    const transport = el("div", { class: "panel glass" });
    const prefs = el("div", { class: "panel glass" });
    const logHost = el("div", { class: "panel glass" });
    page.append(head, transport, prefs, logHost);

    let lastConfig = "";

    const renderTransport = (payload) => {
      const info = payload.transport || {};
      transport.replaceChildren(
        el(
          "div",
          { class: "panel-head" },
          el(
            "div",
            { class: "panel-title" },
            el("h3", { text: "Discord transport" }),
            el("p", { text: "Configured with environment variables only — secrets never reach the browser or the repository." }),
          ),
          info.configured ? badge("PASS", "Configured") : badge("WARNING", "Not configured"),
        ),
        el(
          "div",
          { class: "kv" },
          el("dt", { text: "Mode" }),
          el("dd", { text: humanizeCode(info.mode || "disabled") }),
          el("dt", { text: "Delivery" }),
          el("dd", { text: info.configured ? "Webhook or bot channel ready" : "Set DISCORD_WEBHOOK_URL, or DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID" }),
          el("dt", { text: "Queue" }),
          el("dd", {
            text: `${num((payload.status_counts || {}).PENDING)} pending · ${num((payload.status_counts || {}).QUEUED)} queued · ${num(
              (payload.status_counts || {}).SENT,
            )} sent · ${num((payload.status_counts || {}).FAILED)} failed`,
          }),
        ),
        info.configured
          ? callout({
              tone: "success",
              title: "Delivery is isolated",
              children: "Failed sends stay pending for retry and never raise into the scanner or trade path.",
            })
          : callout({
              tone: "warning",
              title: "Discord not configured",
              children: "The paper lab still works. Add a webhook URL (or a bot token and channel id) as deployment environment variables, then restart the service and send a test.",
            }),
      );
    };

    const renderPrefs = (payload) => {
      const config = payload.config || {};
      const minScore = input({
        type: "number",
        min: "0",
        max: "100",
        step: "1",
        value: String(num(config.min_score_for_alert)),
        "aria-label": "Minimum score for alerts",
      });
      const saveSettings = async () => {
        try {
          await api.saveSettings({
            notifications: {
              enabled: enabledInput.checked,
              min_score_for_alert: num(minScore.value),
              notify_security_warnings: securityInput.checked,
              notify_entries: entriesInput.checked,
              notify_exits: exitsInput.checked,
            },
          });
          toast({ title: "Preferences saved", message: "The dispatcher uses these on the next notification.", type: "success" });
        } catch (error) {
          toastError(error);
        }
      };
      const makeSwitch = (label, checked) =>
        switchControl({
          label,
          checked,
          onChange: saveSettings,
        });
      const enabledInput = makeSwitch("Enable Discord notifications", config.enabled);
      const securityInput = makeSwitch("Notify on security warnings", config.notify_security_warnings);
      const entriesInput = makeSwitch("Notify on paper entries", config.notify_entries);
      const exitsInput = makeSwitch("Notify on paper exits", config.notify_exits);

      prefs.replaceChildren(
        el(
          "div",
          { class: "panel-head" },
          el(
            "div",
            { class: "panel-title" },
            el("h3", { text: "Alert preferences" }),
            el("p", { text: "Saved through the same settings endpoint the Settings page uses." }),
          ),
        ),
        el(
          "div",
          { class: "config-grid" },
          el("div", { class: "config-item" }, field({ label: "Minimum score for alerts", control: minScore, hint: "0–100 opportunity score" })),
          el("div", { class: "config-item" }, entriesInput),
          el("div", { class: "config-item" }, exitsInput),
          el("div", { class: "config-item" }, securityInput),
          el("div", { class: "config-item" }, enabledInput),
        ),
      );
      minScore.addEventListener("change", saveSettings);
    };

    const renderLog = (payload) => {
      const rows = payload.notifications || [];
      const body = rows.length
        ? el(
            "div",
            { class: "notify-list" },
            ...rows.map((item) =>
              el(
                "div",
                { class: "notify-item" },
                el("span", { class: `notify-indicator ${SEVERITIES[severityKey(item.severity)] || "info"}` }),
                el(
                  "div",
                  { class: "notify-body" },
                  el(
                    "div",
                    { class: "notify-title" },
                    el("span", { text: item.title }),
                    statusBadge(item.status),
                    el("span", { class: "badge badge-unknown", text: humanizeCode(item.kind) }),
                  ),
                  el("p", { text: item.message }),
                  el(
                    "div",
                    { class: "notify-meta" },
                    el("span", { text: timeAgo(item.created_at), title: item.created_at || "" }),
                    el("span", { text: `attempts ${int(item.attempts)}` }),
                    item.sent_at ? el("span", { text: `sent ${timeAgo(item.sent_at)}` }) : null,
                    item.last_error ? el("span", { class: "neg", text: item.last_error }) : null,
                  ),
                ),
                el("span", { class: `badge badge-${severityKey(item.severity)}`, text: severityKey(item.severity) }),
              ),
            ),
          )
        : el(
            "div",
            { class: "empty" },
            el("div", { class: "empty-icon", text: "◇" }),
            el("p", { class: "muted", text: "No notifications yet. Entries, exits and security changes are queued automatically." }),
          );

      logHost.replaceChildren(
        el(
          "div",
          { class: "panel-head" },
          el(
            "div",
            { class: "panel-title" },
            el("h3", { text: "Notification log" }),
            el("p", { text: "Newest first. Pending rows are retried by the dispatcher." }),
          ),
          el("span", { class: "result-count", text: `${rows.length} rows` }),
        ),
        body,
      );
    };

    async function refresh() {
      try {
        const payload = await api.notifications(100);
        if (!ctx.isActive()) return;
        renderTransport(payload);
        const configJson = JSON.stringify(payload.config || {});
        if (configJson !== lastConfig) {
          lastConfig = configJson;
          renderPrefs(payload);
        }
        renderLog(payload);
      } catch (error) {
        if (error.name === "AbortError" || !ctx.isActive()) return;
        logHost.replaceChildren(callout({ tone: "danger", title: "Notifications unavailable", children: error.message }));
      }
    }

    testBtn.addEventListener("click", async () => {
      testBtn.disabled = true;
      try {
        const result = await api.testNotification();
        if (!result.configured) {
          toast({ title: "Discord not configured", message: result.detail || "Add the environment variables first.", type: "warning" });
        } else if (result.delivered) {
          toast({ title: "Test delivered", message: `Discord accepted the message via ${result.mode}.`, type: "success" });
        } else {
          toast({ title: "Test queued, delivery failed", message: result.error || "Check the webhook URL and permissions.", type: "error" });
        }
        await refresh();
      } catch (error) {
        toastError(error);
      } finally {
        testBtn.disabled = false;
      }
    });

    dispatchBtn.addEventListener("click", async () => {
      dispatchBtn.disabled = true;
      try {
        const result = await api.dispatchNotifications();
        toast({
          title: result.sent ? "Queue flushed" : "Nothing to send",
          message: result.sent ? `${result.sent} notification(s) delivered.` : "No pending notifications, or Discord is not configured.",
          type: result.sent ? "success" : "info",
        });
        await refresh();
      } catch (error) {
        toastError(error);
      } finally {
        dispatchBtn.disabled = false;
      }
    });

    logHost.replaceChildren(loadingRows(3));
    await refresh();
    poll(ctx, REFRESH_MS, refresh);
    listen(ctx, ["notifications"], refresh);
    onGlobalRefresh(ctx, refresh);

    return page;
  },
};

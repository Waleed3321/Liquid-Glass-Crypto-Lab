/* Small DOM toolkit used by every page. No framework, no build step. */

import { humanizeCode, int, money, num, pct, signClass, signedPct, titleCase } from "./format.js";

const SVG_NS = "http://www.w3.org/2000/svg";

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "value") node.value = value;
    else if (key === "checked" || key === "disabled" || key === "selected") node[key] = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function svg(tag, props = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child == null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  if (!node) return node;
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function mount(node, ...children) {
  clear(node).append(...children.flat(Infinity).filter(Boolean));
  return node;
}

export function panel({ title, subtitle, actions, body, footer, className = "" }) {
  return el(
    "section",
    { class: `panel glass ${className}`.trim() },
    title
      ? el(
          "div",
          { class: "panel-head" },
          el(
            "div",
            { class: "panel-title" },
            el("h3", { text: title }),
            subtitle ? el("p", { text: subtitle }) : null,
          ),
          actions || null,
        )
      : null,
    body ? el("div", { class: "panel-body" }, body) : null,
    footer || null,
  );
}

export function badge(status, label) {
  const raw = String(status || "UNKNOWN").toUpperCase();
  const text = label || humanizeCode(raw);
  return el("span", { class: `badge badge-${raw.toLowerCase()}` }, el("span", { class: "dot" }), text);
}

export function chainBadge(chain) {
  const label = chain === "bsc" ? "BNB Chain" : chain === "solana" ? "Solana" : titleCase(chain);
  return el("span", { class: `badge badge-${chain === "bsc" ? "bsc" : "solana"}` }, label);
}

export function scorePill(score, confidence) {
  const value = num(score);
  const cls = value >= 75 ? "pos" : value >= 50 ? "" : "muted";
  return el(
    "div",
    { class: "score" },
    el("span", { class: `score-value ${cls}`.trim(), text: value.toFixed(1) }),
    el("span", { class: "score-max", text: "/100" }),
    el(
      "span",
      { class: "score-bar", title: `Confidence ${pct(num(confidence) * 100, 1)}` },
      el("i", { style: { width: `${Math.max(2, Math.min(100, value))}%` } }),
    ),
  );
}

export function tokenAvatar(symbol, imageUrl) {
  const node = el("span", { class: "token-avatar", "aria-hidden": "true" });
  const initials = (symbol || "?").replace(/[^a-zA-Z0-9]/g, "").slice(0, 3).toUpperCase() || "?";
  node.textContent = initials;
  if (imageUrl) {
    const img = new Image();
    img.alt = "";
    img.loading = "lazy";
    img.src = imageUrl;
    img.onload = () => {
      node.textContent = "";
      node.append(img);
    };
    img.onerror = () => {};
  }
  return node;
}

export function statTile({ label, value, foot, accent, spark }) {
  const node = el(
    "div",
    { class: "stat glass edge-light" },
    el("span", { class: "stat-label", text: label }),
    el("div", { class: "stat-value", html: "" }, value),
    foot ? el("div", { class: "stat-foot" }, foot) : null,
  );
  if (accent) node.style.setProperty("--accent", accent);
  if (spark) node.append(spark);
  return node;
}

export function meter({ label, value, max, text, tone }) {
  const ratio = Math.max(0, Math.min(1, num(max) > 0 ? num(value) / num(max) : 0));
  return el(
    "div",
    { class: "meter" },
    el(
      "div",
      { class: "meter-head" },
      el("span", { text: label }),
      el("strong", { text: text || `${Math.round(ratio * 100)}%` }),
    ),
    el(
      "div",
      { class: "meter-track" },
      el("div", { class: `meter-fill ${tone || ""}`.trim(), style: { width: `${ratio * 100}%` } }),
    ),
  );
}

export function empty({ icon = "◇", title, message, action }) {
  return el(
    "div",
    { class: "empty" },
    el("div", { class: "empty-icon", text: icon }),
    title ? el("h4", { text: title }) : null,
    message ? el("p", { text: message }) : null,
    action || null,
  );
}

export function loadingRows(count = 4) {
  return el(
    "div",
    {},
    ...Array.from({ length: count }, () =>
      el("div", { class: "skeleton skeleton-row" }),
    ),
  );
}

export function callout({ tone = "info", title, children }) {
  const symbol = { info: "i", warning: "!", danger: "!", success: "✓" }[tone] || "i";
  return el(
    "div",
    { class: `callout ${tone}` },
    el("span", { class: "callout-icon", text: symbol }),
    el("div", {}, title ? el("strong", { text: title }) : null, children ? el("div", {}, children) : null),
  );
}

export function dataTable({ columns, rows, emptyState, onRowClick, rowClass }) {
  if (!rows || rows.length === 0) {
    return emptyState || empty({ title: "Nothing here yet", message: "Data appears as the scanner runs." });
  }
  const head = el(
    "tr",
    {},
    ...columns.map((column) =>
      el("th", {
        class: [column.align === "right" ? "right" : column.align === "center" ? "center" : "", column.sortable ? "sortable" : ""]
          .filter(Boolean)
          .join(" "),
        scope: "col",
        text: column.label,
      }),
    ),
  );
  const body = el(
    "tbody",
    {},
    ...rows.map((row) => {
      const tr = el("tr", {});
      if (rowClass) {
        const cls = rowClass(row);
        if (cls) tr.className = cls;
      }
      if (onRowClick) {
        tr.tabIndex = 0;
        tr.style.cursor = "pointer";
        tr.addEventListener("click", () => onRowClick(row));
        tr.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onRowClick(row);
          }
        });
      }
      for (const column of columns) {
        const cell = el("td", {
          class: column.align === "right" ? "right" : column.align === "center" ? "center" : "",
        });
        const value = column.render ? column.render(row) : row[column.key];
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value == null ? "—" : String(value);
        tr.append(cell);
      }
      return tr;
    }),
  );
  return el(
    "div",
    { class: "table-wrap" },
    el("table", { class: "table" }, el("thead", {}, head), body),
  );
}

export function tabs(items, { active, onChange }) {
  const node = el("div", { class: "tabs", role: "tablist" });
  items.forEach((item) => {
    const button = el("button", {
      class: `tab ${item.value === active ? "active" : ""}`.trim(),
      type: "button",
      role: "tab",
      "aria-selected": item.value === active ? "true" : "false",
      text: item.label,
      onClick: () => onChange(item.value),
    });
    node.append(button);
  });
  return node;
}

let toastStack = null;

export function toast({ title, message, type = "info", timeout = 4200 }) {
  toastStack = toastStack || document.getElementById("toast-stack");
  if (!toastStack) return;
  const node = el(
    "div",
    { class: `toast ${type}`.trim(), role: "status" },
    el("span", { class: "toast-icon" }),
    el(
      "div",
      {},
      el("h5", { text: title || titleCase(type) }),
      message ? el("p", { text: message }) : null,
    ),
  );
  toastStack.append(node);
  const dismiss = () => {
    if (!node.isConnected) return;
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 200);
  };
  node.addEventListener("click", dismiss);
  setTimeout(dismiss, timeout);
}

export function toastError(error) {
  toast({
    title: error && error.code ? humanizeCode(error.code) : "Request failed",
    message: (error && error.message) || "Unexpected error.",
    type: "error",
    timeout: 6000,
  });
}

export function modal({ title, subtitle, body, footer, wide = false }) {
  const dialog = el("dialog", { class: `sheet ${wide ? "wide" : ""}`.trim() });
  const close = () => {
    dialog.close();
    dialog.remove();
  };
  const head = el(
    "div",
    { class: "dialog-head" },
    el(
      "div",
      {},
      el("h3", { text: title || "" }),
      subtitle ? el("p", { text: subtitle }) : null,
    ),
    el("button", { class: "btn btn-ghost btn-icon btn-sm", type: "button", "aria-label": "Close", text: "✕", onClick: close }),
  );
  dialog.append(
    head,
    el("div", { class: "dialog-body" }, body),
    footer ? el("div", { class: "dialog-foot" }, footer) : null,
  );
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  document.body.append(dialog);
  dialog.showModal();
  return { dialog, close };
}

export function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const footer = el(
      "div",
      { class: "row" },
      el("button", {
        class: "btn",
        type: "button",
        text: "Cancel",
        onClick: () => {
          modalRef.close();
          resolve(false);
        },
      }),
      el("button", {
        class: `btn ${danger ? "btn-danger" : "btn-primary"}`.trim(),
        type: "button",
        text: confirmLabel,
        onClick: () => {
          modalRef.close();
          resolve(true);
        },
      }),
    );
    const modalRef = modal({ title, body: el("p", { class: "muted", text: message }), footer });
  });
}

export function field({ label, hint, control }) {
  return el(
    "div",
    { class: "field" },
    label ? el("label", { text: label }) : null,
    control,
    hint ? el("span", { class: "hint", text: hint }) : null,
  );
}

export function input(props = {}) {
  return el("input", { class: "input", ...props });
}

export function select(options, props = {}) {
  const node = el("select", { class: "select", ...props });
  options.forEach((option) => {
    const { value, label } = typeof option === "string" ? { value: option, label: option } : option;
    node.append(el("option", { value, text: label, selected: String(value) === String(props.value) }));
  });
  return node;
}

export function switchControl({ label, checked, onChange }) {
  const inputNode = el("input", { type: "checkbox", checked: Boolean(checked) });
  inputNode.addEventListener("change", () => onChange(inputNode.checked));
  return el(
    "label",
    { class: "switch" },
    inputNode,
    el("span", { class: "switch-track", "aria-hidden": "true" }),
    el("span", { text: label }),
  );
}

export function moneyCell(value, { signed = false, digits = 2 } = {}) {
  const n = num(value);
  const text = signed ? `${n > 0 ? "+" : n < 0 ? "-" : ""}${money(Math.abs(n), digits)}` : money(n, digits);
  return el("span", { class: `numeric ${signed ? signClass(n) : ""}`.trim(), text });
}

export function pctCell(value, digits = 2, signed = true) {
  const n = num(value);
  return el("span", {
    class: `numeric ${signed ? signClass(n) : ""}`.trim(),
    text: signed ? signedPct(n, digits) : pct(n, digits),
  });
}

export function countCell(value) {
  return el("span", { class: "numeric", text: int(value) });
}

export function progressRing(value, label, caption) {
  const v = Math.max(0, Math.min(100, num(value)));
  return el(
    "div",
    { class: "ring", style: { "--ring-value": v } },
    el(
      "div",
      { class: "ring-inner" },
      el("strong", { text: Math.round(v) }),
      el("span", { text: label || "score" }),
    ),
    caption ? el("span", { class: "ring-caption", text: caption }) : null,
  );
}

export function pageHead({ title, description, actions, eyebrow }) {
  return el(
    "div",
    { class: "page-head" },
    el(
      "div",
      {},
      eyebrow ? el("span", { class: "label", text: eyebrow }) : null,
      el("h2", { text: title }),
      description ? el("p", { text: description }) : null,
    ),
    actions ? el("div", { class: "page-actions" }, actions) : null,
  );
}

export function debounce(fn, wait = 260) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function iconButton({ label, text, onClick, title }) {
  return el("button", {
    class: "btn btn-sm btn-ghost",
    type: "button",
    "aria-label": label,
    title: title || label,
    text,
    onClick,
  });
}

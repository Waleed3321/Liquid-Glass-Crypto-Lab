/**
 * Runtime configuration.
 *
 * Leave `apiBase` empty when the dashboard is served by FastAPI itself
 * (same origin). Set it to the deployed API origin when the dashboard is
 * hosted separately, for example:
 *
 *   window.LAB_CONFIG = { apiBase: "https://liquid-glass-lab.onrender.com" };
 */
window.LAB_CONFIG = {
  apiBase: "",
  refreshMs: 30000,
  title: "Liquid Glass Crypto Lab",
};

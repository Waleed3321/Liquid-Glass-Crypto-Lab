#!/usr/bin/env node
/* Build the deployable artifacts.
 *
 * There is no JS bundler: the dashboard is plain ES modules served by FastAPI.
 * The build therefore syntax-checks the Python app and exports the static
 * dashboard for a static host with the API origin injected.
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const apiBase = process.env.API_BASE ?? "http://127.0.0.1:8000";

function run(cmd, args) {
  const result = spawnSync(cmd, args, { cwd: root, stdio: "inherit" });
  if (result.error) throw new Error(`${cmd}: ${result.error.message}`);
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const local = process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python";
const python = [process.env.PYTHON, local].filter(Boolean).find((p) => existsSync(resolve(root, p)));
if (!python) throw new Error("no Python interpreter: create .venv or set PYTHON");

run(python, ["-m", "compileall", "-q", "app", "migrations", "scripts"]);
run(python, ["scripts/export_static.py", "--api-base", apiBase]);

const config = readFileSync(resolve(root, "dist/config.js"), "utf8");
if (!config.includes(apiBase)) throw new Error("dist/config.js is missing the API base");
if (!readFileSync(resolve(root, "dist/index.html"), "utf8").includes("js/main.js")) {
  throw new Error("dist/index.html does not boot the dashboard");
}
console.log(`build ok: dist/ (api base ${apiBase})`);

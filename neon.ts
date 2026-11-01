import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  // Declare your Neon services here
  preview: {
    realtime: true,
  },
  auth: true,
  // AI Gateway is declared off: Neon refuses to apply it on the Free plan and
  // the project must stay on free infrastructure.
  aiGateway: false,
  functions: {
    hello: { name: "Hello World", source: "./hello.ts" },
    keepalive: { name: "Render keep-alive", source: "./keepalive.ts" },
  },
  triggers: {
    // Free Render web services sleep after ~15 idle minutes; this cron keeps the
    // API and its in-process scanner loop awake with no developer machine.
    "render-keepalive": {
      type: "schedule",
      function: "keepalive",
      cron: "*/5 * * * *",
    },
  },
  buckets: {
    // "private" is the default; use "public_read" for anonymous reads
    assets: { access: "private" },
  },
  // Branch policy: per-branch tuning
  branch: (branch) => {
    if (branch.isDefault) {
      // Default branch: no overrides, uses project defaults
      return {};
    }
    if (!branch.exists) {
      // New non-default branches: auto-expire
      // Run `neon checkout <name>` to create a new branch with these settings
      return { ttl: "7d" };
    }
    // Existing branch: no changes
    return {};
  },
});

import { defineConfig } from "@playwright/test";

import baseConfig from "./playwright.config";

export default defineConfig({
  ...baseConfig,
  testDir: "./audit",
  retries: 0,
  reporter: "list",
});

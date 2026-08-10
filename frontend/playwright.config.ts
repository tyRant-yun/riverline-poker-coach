import { defineConfig } from "@playwright/test";
import path from "node:path";

const workspaceRoot = path.resolve(__dirname, "..");

// Deploy-mode runs: PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 skips the
// local webServers and tests the compose deployment (web -> nginx -> api).
const deployBaseURL = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: deployBaseURL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  webServer: deployBaseURL
    ? undefined
    : [
        {
          command: "py -3.13 -m uvicorn poker_coach.api.app:app --app-dir backend --port 8000",
          cwd: workspaceRoot,
          url: "http://127.0.0.1:8000/health",
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
        {
          command: "npm run dev -- --hostname 127.0.0.1 --port 3000",
          cwd: __dirname,
          url: "http://127.0.0.1:3000",
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      ],
});

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["components/**/*.test.{ts,tsx}", "features/**/*.test.{ts,tsx}", "lib/**/*.test.{ts,ts}"],
  },
});

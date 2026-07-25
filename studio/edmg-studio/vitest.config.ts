import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { reactCompilerBabel } from "./reactCompilerOptions";

export default defineConfig({
  plugins: [react({ babel: reactCompilerBabel })],
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});

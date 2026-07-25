import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const widgetRoot = fileURLToPath(new URL("./src/widget", import.meta.url));
const assetsDir = fileURLToPath(new URL("./assets", import.meta.url));

export default defineConfig({
  base: "./",
  root: widgetRoot,
  plugins: [react()],
  build: {
    outDir: assetsDir,
    emptyOutDir: true,
    assetsDir: ".",
    rollupOptions: {
      input: "review-board.html",
    },
  },
});

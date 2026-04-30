import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "assets",
    emptyOutDir: true,
    assetsDir: ".",
    rollupOptions: {
      input: {
        "review-board": path.resolve(__dirname, "src/widget/review-board.html"),
      },
    },
  },
});

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
      input: "src/widget/review-board.html",
    },
  },
});

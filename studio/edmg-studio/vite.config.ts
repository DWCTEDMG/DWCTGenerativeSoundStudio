import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { reactCompilerBabel } from "./reactCompilerOptions";

export default defineConfig({
  base: "./",
  plugins: [react({ babel: reactCompilerBabel })],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      ignored: [
        "**/.cache/**",
        "**/cache/**",
        "**/data/**",
        "**/dist/**",
        "**/external/**",
        "**/logs/**",
        "**/models/**",
        "**/python_backend/build/**",
        "**/python_backend/dist/**",
        "**/python_backend/venv/**",
        "**/release/**",
      ],
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: "dist-web",
    emptyOutDir: true,
  },
});

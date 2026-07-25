import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { reactCompilerBabel } from "./reactCompilerOptions";

export default defineConfig({
  base: "./",
  // Studio routes via ?page= (not path history). SPA HTML fallback turns missing
  // /src/*.tsx into index.html (200 text/html), which Electron then parses as JS
  // → "Uncaught SyntaxError: Invalid or unexpected token" at line 1.
  appType: "mpa",
  plugins: [react({ babel: reactCompilerBabel })],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    warmup: {
      clientFiles: [
        "./src/main.tsx",
        "./src/App.tsx",
        "./src/pages/Dashboard.tsx",
        "./src/pages/Projects.tsx",
        "./src/components/StudioLayoutCustomizer.tsx",
        "./src/components/studioLayout.ts",
      ],
    },
    watch: {
      ignored: [
        "**/.cache/**",
        "**/cache/**",
        "**/data/**",
        "**/dist/**",
        "**/electron/**",
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

/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8")) as {
  version: string;
};

// Mirrors the production nginx headers so problems show up in development too.
// CSP is left to production: the dev server's HMR client needs inline scripts.
const securityHeaders = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
};

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // loadEnv returns "" for unset keys in some setups, so fall back on any empty value.
  const apiTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    define: {
      __APP_VERSION__: JSON.stringify(pkg.version),
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      headers: securityHeaders,
      watch: env.VITE_USE_POLLING === "true" ? { usePolling: true, interval: 300 } : undefined,
      // Same-origin API in development: no CORS, and auth cookies work as in production.
      proxy: {
        "/api": { target: apiTarget, changeOrigin: false, xfwd: true },
      },
    },
    preview: { port: 4173, headers: securityHeaders },
    build: {
      sourcemap: false,
      target: "es2022",
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
      restoreMocks: true,
      // userEvent typing in long forms is slow under parallel load; keep CI from flaking.
      testTimeout: 15_000,
      unstubGlobals: true,
      coverage: {
        provider: "v8",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/main.tsx", "src/test/**", "src/**/*.d.ts"],
        thresholds: { lines: 85, functions: 85, branches: 80, statements: 85 },
      },
    },
  };
});

/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, loadEnv, transformWithOxc, type Plugin } from "vite";

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

// Files from public/ that belong to the app shell, stored by the service worker on install.
const PUBLIC_SHELL = [
  "/favicon.svg",
  "/theme-init.js",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
  "/icons/apple-touch-icon.png",
];

/**
 * Builds /sw.js from src/pwa/sw.ts (ADR 0018): the types and `export`s stripped, and the list of
 * files to store on install in front. Its version is a hash of everything it stores, so any
 * release that changes the app changes sw.js, which is how browsers notice a new version.
 */
function serviceWorker(): Plugin {
  let root = "";
  return {
    name: "sitesense-service-worker",
    apply: "build",
    enforce: "post",
    configResolved(config) {
      root = config.root;
    },
    async generateBundle(_options, bundle) {
      const built = Object.keys(bundle)
        .filter((name) => /^assets\/.+\.(js|css)$/.test(name))
        .sort()
        .map((name) => `/${name}`);
      const files = ["/", ...built, ...PUBLIC_SHELL];
      const source = readFileSync(resolve(root, "src/pwa/sw.ts"), "utf-8");
      const hash = createHash("sha256").update(source);
      for (const name of files) hash.update(name);
      for (const name of PUBLIC_SHELL) hash.update(readFileSync(resolve(root, "public", `.${name}`)));
      const index = Object.hasOwn(bundle, "index.html") ? bundle["index.html"] : undefined;
      if (index?.type === "asset") hash.update(index.source);
      const version = hash.digest("hex").slice(0, 12);
      const { code } = await transformWithOxc(source, "sw.ts");
      const script = `const PRECACHE = ${JSON.stringify({ version, files })};
${code.replace(/^export /gm, "")}`;
      this.emitFile({ type: "asset", fileName: "sw.js", source: script });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // loadEnv returns "" for unset keys in some setups, so fall back on any empty value.
  const apiTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss(), serviceWorker()],
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
    // The built app (with its service worker), same-origin API as in development.
    preview: {
      port: 4173,
      headers: securityHeaders,
      proxy: { "/api": { target: apiTarget, changeOrigin: false, xfwd: true } },
    },
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

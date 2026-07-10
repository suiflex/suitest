import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { TanStackRouterVite } from "@tanstack/router-vite-plugin";
import path from "node:path";

export default defineConfig({
  plugins: [TanStackRouterVite(), react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 3000,
    host: "0.0.0.0",
    strictPort: true,
    proxy: {
      // Backend mounts these paths at the application root (NOT under /api/v1).
      // Add all root-mounted paths here so dev requests are forwarded to the
      // FastAPI server instead of falling through to Vite's SPA index.html.
      "/api": "http://localhost:4000",
      "/auth": "http://localhost:4000",
      "/capabilities": "http://localhost:4000",
      "/health": "http://localhost:4000",
      "/metrics": "http://localhost:4000",
      "/openapi.json": "http://localhost:4000",
      "/ws": { target: "ws://localhost:4000", ws: true },
    },
  },
  preview: { port: 3000 },
  // Pin the dep pre-bundler to the same modern target as the build. Vite's
  // default optimizer target ("chrome87"/"es2020"…) can trip esbuild into a
  // spurious "Transforming destructuring … is not supported yet" on some deps
  // (e.g. sonner), which crashes the dev server. es2022 supports destructuring
  // natively, so nothing is down-transformed.
  optimizeDeps: { esbuildOptions: { target: "es2022" } },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
    rollupOptions: {
      output: {
        // Split heavy vendor libs into their own chunks so the main bundle
        // stays lean and we only ship recharts when the dashboard pass-rate
        // chart lazy-mounts. Verified post-build: main chunk ~150-180KB gzip,
        // recharts ships as a separate `recharts-*.js`.
        manualChunks: {
          recharts: ["recharts"],
          // The unified `radix-ui` entry point pulls the individual
          // @radix-ui/react-* primitives (its dependencies) into this chunk.
          radix: ["radix-ui"],
          tanstack: ["@tanstack/react-router", "@tanstack/react-query"],
        },
      },
    },
  },
});

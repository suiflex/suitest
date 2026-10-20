import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { TanStackRouterVite } from "@tanstack/router-vite-plugin";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const rootDir = path.resolve(__dirname, "../../");
  const env = loadEnv(mode, rootDir, "");
  const backendPort =
    process.env.VITE_BACKEND_PORT ||
    env.VITE_BACKEND_PORT ||
    process.env.SUITEST_API_PORT ||
    env.SUITEST_API_PORT ||
    "4000";
  const backendTarget = `http://localhost:${backendPort}`;
  const wsTarget = `ws://localhost:${backendPort}`;

  return {
    envDir: rootDir,
    plugins: [TanStackRouterVite(), react(), tailwindcss()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      port: process.env.VITE_PORT
        ? parseInt(process.env.VITE_PORT, 10)
        : env.VITE_PORT
          ? parseInt(env.VITE_PORT, 10)
          : 3000,
      host: "0.0.0.0",
      strictPort: true,
      proxy: {
        "/api": { target: backendTarget, changeOrigin: true },
        "/auth": { target: backendTarget, changeOrigin: true },
        "/capabilities": { target: backendTarget, changeOrigin: true },
        "/health": { target: backendTarget, changeOrigin: true },
        "/metrics": { target: backendTarget, changeOrigin: true },
        "/openapi.json": { target: backendTarget, changeOrigin: true },
        "/ws": { target: wsTarget, ws: true },
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
  };
});


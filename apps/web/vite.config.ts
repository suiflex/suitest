import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 3000,
    host: "0.0.0.0",
    strictPort: true,
  },
  preview: { port: 3000 },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
  },
});

/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    rollupOptions: {
      output: {
        // Long-lived vendor chunks cache across deploys; app code changes don't bust them.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          data: ["@tanstack/react-query", "zod", "react-hook-form", "@hookform/resolvers"],
          ui: ["@radix-ui/react-dialog", "@radix-ui/react-alert-dialog", "@radix-ui/react-tabs", "@radix-ui/react-switch", "@radix-ui/react-progress", "@radix-ui/react-label", "@radix-ui/react-slot", "sonner", "lucide-react"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});

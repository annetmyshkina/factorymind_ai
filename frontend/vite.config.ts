import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPaths = [
  "/health",
  "/equipment",
  "/incidents",
  "/knowledge",
  "/evaluations",
  "/ai",
  "/experiments",
];

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      apiPaths.map((path) => [path, "http://127.0.0.1:8000"]),
    ),
  },
});

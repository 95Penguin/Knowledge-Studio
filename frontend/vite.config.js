import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8001",
      "/backend": {
        target: "http://127.0.0.1:8080",
        rewrite: (path) => path.replace(/^\/backend/, ""),
      },
    },
  },
});

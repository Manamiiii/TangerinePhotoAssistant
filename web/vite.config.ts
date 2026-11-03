import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    // Vite checks both the file and raw module ID; allow only this shared document.
    fs: { allow: [".", "../LICENSE", "../LICENSE?raw"] },
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
});

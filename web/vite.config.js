import { defineConfig } from "vite";

// 前端开发服务器：改 app.js / style.css 即自动刷新；/api 代理到本地后端 8300
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8300",
    },
  },
});

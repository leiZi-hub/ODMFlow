/**
 * 用途：配置 Vite 构建与同源开发代理。
 * 边界：DEV_API_TARGET 仅在 Node 侧读取，不暴露给浏览器。
 */
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

import {
  apiProxyKey,
  parseDevApiTarget,
  rewriteApiPath,
} from "./config/devProxy.ts";
import { parseApiBasePath } from "./src/shared/config/apiPath.ts";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const basePath = parseApiBasePath(env.VITE_API_BASE_PATH);
  const target = parseDevApiTarget(env.DEV_API_TARGET);

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        [apiProxyKey(basePath)]: {
          target,
          changeOrigin: false,
          rewrite: (path: string) => rewriteApiPath(path, basePath),
        },
      },
    },
  };
});

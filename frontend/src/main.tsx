/**
 * 用途：挂载前端应用和仅驻留内存的身份查询缓存。
 * 边界：不持久化身份，不在入口处理业务请求。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./styles/tokens.css";
import "./styles/global.css";

const root = document.getElementById("root");
if (root === null) throw new Error("缺少 #root 挂载节点");
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);

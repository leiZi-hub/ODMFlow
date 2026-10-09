/**
 * 用途：集中暴露浏览器可见的公开配置。
 * 边界：不包含 API Key、代理目标或任何本机私有值。
 */
import { parseApiBasePath } from "./apiPath";

export const publicConfig: Readonly<{ apiBasePath: string }> = Object.freeze({
  apiBasePath: parseApiBasePath(import.meta.env.VITE_API_BASE_PATH),
});

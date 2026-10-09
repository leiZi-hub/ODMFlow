/**
 * 用途：校验浏览器与开发代理共享的同源 API 前缀。
 * 边界：只处理公开路径，不读取环境或发起网络请求。
 */
const API_PATH_PATTERN = /^\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/;

/** 解析根相对 API 前缀；未提供时使用 /api，非法输入抛出错误。 */
export function parseApiBasePath(raw: string | undefined): string {
  const value = raw === undefined ? "/api" : raw;
  if (!API_PATH_PATTERN.test(value)) {
    throw new Error("VITE_API_BASE_PATH 必须是非空根相对路径且不得以 / 结尾");
  }
  return value;
}

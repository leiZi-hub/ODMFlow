/**
 * 用途：构造开发期同源代理的目标与路径映射。
 * 边界：只供 Vite 的 Node 进程使用，不进入浏览器产物。
 */
/** 解析后端开发目标；仅允许不含凭证和附加路径的 HTTP(S) origin。 */
export function parseDevApiTarget(raw: string | undefined): string {
  const value = raw === undefined ? "http://127.0.0.1:8000" : raw;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("DEV_API_TARGET 必须是无凭证的 HTTP(S) origin");
  }

  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username !== "" ||
    url.password !== "" ||
    value !== url.origin
  ) {
    throw new Error(
      "DEV_API_TARGET 必须是无凭证、路径、查询和片段的 HTTP(S) origin",
    );
  }
  return url.origin;
}

/** 返回仅匹配完整 API 路径段的 Vite 代理键。 */
export function apiProxyKey(basePath: string): string {
  return `^${basePath}(?:/|\\?|$)`;
}

/** 去掉 API 前缀，保留后端路径和查询参数。 */
export function rewriteApiPath(path: string, basePath: string): string {
  if (!new RegExp(apiProxyKey(basePath)).test(path)) {
    throw new Error("请求路径不属于配置的 API 前缀");
  }

  const suffix = path.slice(basePath.length);
  if (suffix === "") return "/";
  return suffix.startsWith("?") ? `/${suffix}` : suffix;
}

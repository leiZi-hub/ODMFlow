/**
 * 用途：统一发起同源 API 请求并归类网络/HTTP 错误。
 * 边界：只接受站点内纯路径，不解析或展示服务端错误详情。
 */
import { publicConfig } from "../config/publicConfig";

export class ApiError extends Error {
  readonly status: number | null;

  /** 状态码为空表示网络层失败；其余值为服务端 HTTP 状态。 */
  constructor(status: number | null) {
    super("API 请求失败");
    this.name = "ApiError";
    this.status = status;
  }
}

/** 输入为不带查询/片段的内部路径；返回成功响应，失败抛出 ApiError。 */
export async function apiRequest(
  path: string,
  init?: RequestInit,
  search?: URLSearchParams,
): Promise<Response> {
  if (!/^\/[A-Za-z0-9/_-]+$/.test(path) || path.includes("..")) {
    throw new Error("API 路径必须是站点内的纯路径");
  }

  let response: Response;
  try {
    const query = search?.size ? `?${search.toString()}` : "";
    response = await fetch(`${publicConfig.apiBasePath}${path}${query}`, {
      ...init,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(null);
  }
  if (!response.ok) throw new ApiError(response.status);
  return response;
}

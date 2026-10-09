/**
 * 用途：封装五个身份接口及响应契约。
 * 边界：不缓存口令、Cookie、CSRF token 或用户身份。
 */
import { ApiError, apiRequest } from "../../shared/api/http";

export type Credentials = { username: string; password: string };
export type CurrentIdentity = { user_id: string; username: string };

/** 检查服务端身份响应，避免畸形内容被当作已认证用户。 */
async function readIdentity(response: Response): Promise<CurrentIdentity> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(null);
  }
  if (
    typeof body !== "object" ||
    body === null ||
    !("user_id" in body) ||
    !("username" in body) ||
    typeof body.user_id !== "string" ||
    typeof body.username !== "string" ||
    body.user_id.trim() === "" ||
    body.username.trim() === ""
  ) {
    throw new ApiError(null);
  }
  return { user_id: body.user_id, username: body.username };
}

/** 注册账号并返回后端规范化的身份；注册不代表登录。 */
export async function registerAccount(
  input: Credentials,
): Promise<CurrentIdentity> {
  const response = await apiRequest("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readIdentity(response);
}

/** 提交凭证，Cookie 由浏览器处理；调用方还须查询 /me。 */
export async function loginAccount(input: Credentials): Promise<void> {
  await apiRequest("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

/** 仅将 401 解释为游客；网络及其他 HTTP 故障继续抛出。 */
export async function getCurrentIdentity(): Promise<CurrentIdentity | null> {
  try {
    return await readIdentity(await apiRequest("/auth/me"));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/** 只为紧随其后的退出请求读取一次 CSRF token。 */
export async function getCsrfToken(): Promise<string> {
  const response = await apiRequest("/auth/csrf");
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(null);
  }
  if (
    typeof body !== "object" ||
    body === null ||
    !("csrf_token" in body) ||
    typeof body.csrf_token !== "string" ||
    body.csrf_token.trim() === ""
  ) {
    throw new ApiError(null);
  }
  return body.csrf_token;
}

/** 先取 CSRF token 再退出；前一步失败时不会发送退出请求。 */
export async function logoutAccount(): Promise<void> {
  const csrfToken = await getCsrfToken();
  await apiRequest("/auth/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
}

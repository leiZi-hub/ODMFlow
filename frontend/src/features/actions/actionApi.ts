/** 用途：同源确认卡API与严格边界解析；不缓存身份、确认参数或凭据。 */
import { ApiError, apiRequest } from "../../shared/api/http";
import { getCsrfToken } from "../auth/authApi";
import { isRecord } from "../conversations/operationTypes";

export type ActionStatus =
  | "pending_confirmation"
  | "succeeded"
  | "cancelled"
  | "expired"
  | "invalidated";
export type BusinessAction = {
  id: string;
  kind: "order_application" | "after_sales_application";
  status: ActionStatus;
  revision: number;
  conversation_id: string;
  turn_id: string;
  simulated: true;
  parameters: Record<string, string | number | null>;
  expires_at: string;
  result: { business_no: string; status: string; simulated: true } | null;
};
export type ActionPage = { items: BusinessAction[]; has_more: boolean };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** 后端快照必须为模拟、正确类型及版本，不能把畸形结果显示为成功。 */
export function readAction(value: unknown): BusinessAction {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !uuid.test(value.id) ||
    typeof value.conversation_id !== "string" ||
    !uuid.test(value.conversation_id) ||
    typeof value.turn_id !== "string" ||
    !uuid.test(value.turn_id) ||
    value.simulated !== true ||
    !["order_application", "after_sales_application"].includes(
      String(value.kind),
    ) ||
    ![
      "pending_confirmation",
      "succeeded",
      "cancelled",
      "expired",
      "invalidated",
    ].includes(String(value.status)) ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) < 1 ||
    typeof value.expires_at !== "string" ||
    !Number.isFinite(Date.parse(value.expires_at)) ||
    !isRecord(value.parameters)
  )
    throw new ApiError(null);
  const parameters: Record<string, string | number | null> = {};
  for (const [key, item] of Object.entries(value.parameters)) {
    if (
      item !== null &&
      typeof item !== "string" &&
      !(typeof item === "number" && Number.isFinite(item))
    )
      throw new ApiError(null);
    parameters[key] = item as string | number | null;
  }
  let result: BusinessAction["result"] = null;
  if (value.result !== null) {
    if (
      !isRecord(value.result) ||
      typeof value.result.business_no !== "string" ||
      !value.result.business_no ||
      typeof value.result.status !== "string" ||
      value.result.simulated !== true
    )
      throw new ApiError(null);
    result = {
      business_no: value.result.business_no,
      status: value.result.status,
      simulated: true,
    };
  }
  if ((value.status === "succeeded") !== (result !== null))
    throw new ApiError(null);
  return {
    id: value.id,
    kind: value.kind as BusinessAction["kind"],
    status: value.status as ActionStatus,
    revision: Number(value.revision),
    conversation_id: value.conversation_id,
    turn_id: value.turn_id,
    simulated: true,
    parameters,
    expires_at: value.expires_at,
    result,
  };
}

/** 只读取当前会话的有界确认卡；identity始终由Cookie决定。 */
export async function listActions(
  conversationId: string,
  offset = 0,
  signal?: AbortSignal,
): Promise<ActionPage> {
  const response = await apiRequest(
    "/agent/actions",
    { signal },
    new URLSearchParams({
      conversation_id: conversationId,
      limit: "10",
      offset: String(offset),
    }),
  );
  const value: unknown = await response.json();
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    value.items.length > 10 ||
    typeof value.has_more !== "boolean"
  )
    throw new ApiError(null);
  const items = value.items.map(readAction);
  if (
    items.some((item) => item.conversation_id !== conversationId) ||
    new Set(items.map((item) => item.id)).size !== items.length
  )
    throw new ApiError(null);
  return { items, has_more: value.has_more };
}

/** 写结果不明时只查询同一动作，不自动重放确认。 */
export async function getAction(
  id: string,
  signal?: AbortSignal,
): Promise<BusinessAction> {
  if (!uuid.test(id)) throw new ApiError(null);
  const value = readAction(
    await (await apiRequest(`/agent/actions/${id}`, { signal })).json(),
  );
  if (value.id !== id) throw new ApiError(null);
  return value;
}

/** 写请求只revision与现取CSRF；未执行动作不由客户端预先标成功。 */
export async function decideAction(
  action: BusinessAction,
  confirmed: boolean,
  signal?: AbortSignal,
): Promise<BusinessAction> {
  const token = await getCsrfToken();
  if (signal?.aborted) throw new ApiError(null);
  const response = await apiRequest(
    `/agent/actions/${action.id}/${confirmed ? "confirm" : "cancel"}`,
    {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ revision: action.revision }),
    },
  );
  const result = readAction(await response.json());
  if (
    result.id !== action.id ||
    result.conversation_id !== action.conversation_id
  )
    throw new ApiError(null);
  return result;
}

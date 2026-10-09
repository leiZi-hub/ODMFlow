/** 用途：封装私人对话列表、历史和受保护的流式发送；边界：不保存身份或消息。 */
import { getCsrfToken } from "../auth/authApi";
import { ApiError, apiRequest } from "../../shared/api/http";
import { readOperation, type OperationSummary } from "./operationTypes";
import {
  consumeConversationStream,
  readMessage,
  type ConversationMessage,
  type ConversationStreamEvent,
} from "./streamEvents";

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};
export type ConversationPage = { items: Conversation[]; has_more: boolean };
export type MessagePage = {
  items: ConversationMessage[];
  next_before_id: number | null;
};
export type SendTurnInput = {
  message: string;
  client_turn_id: string;
  conversation_id?: string;
};

/** 按需读取本人轮次；权限由后端计算，不传客户端调试开关。 */
export async function listTurnOperations(
  conversationId: string,
  turnId: string,
  signal?: AbortSignal,
): Promise<{ items: OperationSummary[]; details_available: boolean }> {
  const body = await readJson(
    await apiRequest(
      `/conversations/${conversationId}/turns/${turnId}/operations`,
      { signal },
    ),
  );
  if (
    !isRecord(body) ||
    !Array.isArray(body.items) ||
    typeof body.details_available !== "boolean"
  )
    throw new ApiError(null);
  const items = body.items.map(readOperation);
  if (items.some((item) => item.turn_id !== turnId)) throw new ApiError(null);
  return { items, details_available: body.details_available };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiError(null);
  }
}

function readConversation(value: unknown): Conversation {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.title !== "string" ||
    typeof value.created_at !== "string" ||
    typeof value.updated_at !== "string"
  )
    throw new ApiError(null);
  return {
    id: value.id,
    title: value.title,
    created_at: value.created_at,
    updated_at: value.updated_at,
  };
}

/** 读取当前登录账号的对话页。 */
export async function listConversations(
  limit = 30,
  offset = 0,
): Promise<ConversationPage> {
  const search = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const body = await readJson(
    await apiRequest("/conversations", undefined, search),
  );
  if (
    !isRecord(body) ||
    !Array.isArray(body.items) ||
    typeof body.has_more !== "boolean"
  )
    throw new ApiError(null);
  return { items: body.items.map(readConversation), has_more: body.has_more };
}

/** 读取指定私人对话的一页历史。 */
export async function listMessages(
  conversationId: string,
  limit = 30,
  beforeId?: number,
): Promise<MessagePage> {
  const search = new URLSearchParams({ limit: String(limit) });
  if (beforeId !== undefined) search.set("before_id", String(beforeId));
  const body = await readJson(
    await apiRequest(
      `/conversations/${conversationId}/messages`,
      undefined,
      search,
    ),
  );
  if (
    !isRecord(body) ||
    !Array.isArray(body.items) ||
    (body.next_before_id !== null &&
      (typeof body.next_before_id !== "number" ||
        !Number.isSafeInteger(body.next_before_id)))
  )
    throw new ApiError(null);
  const items = body.items.map(readMessage);
  if (items.some((item) => item.conversation_id !== conversationId))
    throw new ApiError(null);
  return { items, next_before_id: body.next_before_id };
}

/** 发送本轮消息并消费直到持久化终态。 */
export async function sendConversationTurn(
  input: SendTurnInput,
  onEvent: (event: ConversationStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const csrf = await getCsrfToken();
  const response = await apiRequest("/agent/turns/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(input),
    signal,
  });
  await consumeConversationStream(response, onEvent);
}

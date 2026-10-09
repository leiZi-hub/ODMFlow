/** 用途：解析并校验对话 SSE 事件；边界：不发起请求或修改界面状态。 */
import {
  readOperation,
  readSource,
  type OperationSummary,
  type Citation,
} from "./operationTypes";
export type ConversationMessage = {
  id: number;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  kind: "normal" | "fallback";
  created_at: string;
  turn_id?: string | null;
  operations?: OperationSummary[];
  citations?: Citation[];
  details_available?: boolean;
};

export type ConversationStreamEvent =
  | {
      type: "accepted";
      conversation_id: string;
      user_message: ConversationMessage;
      turn_id?: string;
      details_available?: boolean;
    }
  | { type: "token"; text: string }
  | {
      type: "operation_started" | "operation_finished";
      operation: OperationSummary;
    }
  | {
      type: "completed";
      assistant_message: ConversationMessage;
      outcome: "completed" | "failed" | "interrupted";
    }
  | { type: "error"; code: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** 校验后端用户可见消息，供历史读取和事件流共用。 */
export function readMessage(value: unknown): ConversationMessage {
  if (
    !isRecord(value) ||
    typeof value.id !== "number" ||
    !Number.isSafeInteger(value.id) ||
    typeof value.conversation_id !== "string" ||
    (value.role !== "user" && value.role !== "assistant") ||
    typeof value.content !== "string" ||
    (value.kind !== "normal" && value.kind !== "fallback") ||
    typeof value.created_at !== "string" ||
    (value.operations !== undefined && !Array.isArray(value.operations)) ||
    (value.citations !== undefined && !Array.isArray(value.citations)) ||
    (value.turn_id !== undefined &&
      value.turn_id !== null &&
      typeof value.turn_id !== "string") ||
    (value.details_available !== undefined &&
      typeof value.details_available !== "boolean")
  ) {
    throw new Error("对话消息格式无效");
  }
  return {
    id: value.id,
    conversation_id: value.conversation_id,
    role: value.role,
    content: value.content,
    kind: value.kind,
    created_at: value.created_at,
    ...(value.turn_id === null || typeof value.turn_id === "string"
      ? { turn_id: value.turn_id }
      : {}),
    ...(Array.isArray(value.operations)
      ? { operations: value.operations.map(readOperation) }
      : {}),
    ...(typeof value.details_available === "boolean"
      ? { details_available: value.details_available }
      : {}),
    ...(Array.isArray(value.citations)
      ? {
          citations: value.citations.map((item) => {
            if (
              !isRecord(item) ||
              typeof item.text !== "string" ||
              typeof item.source_path !== "string"
            )
              throw new Error("引用格式无效");
            return {
              ...readSource(item),
              text: item.text,
              source_path: item.source_path,
            };
          }),
        }
      : {}),
  };
}

function readEvent(name: string, raw: string): ConversationStreamEvent {
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    throw new Error("对话事件格式无效");
  }
  if (!isRecord(body)) throw new Error("对话事件格式无效");
  if (name === "accepted" && typeof body.conversation_id === "string") {
    const userMessage = readMessage(body.user_message);
    if (
      userMessage.role !== "user" ||
      userMessage.conversation_id !== body.conversation_id
    )
      throw new Error("对话事件格式无效");
    return {
      type: "accepted",
      conversation_id: body.conversation_id,
      user_message: userMessage,
      ...(typeof body.turn_id === "string" ? { turn_id: body.turn_id } : {}),
      ...(typeof body.details_available === "boolean"
        ? { details_available: body.details_available }
        : {}),
    };
  }
  if (name === "token" && typeof body.text === "string" && body.text.length > 0)
    return { type: "token", text: body.text };
  if (name === "operation_started" || name === "operation_finished") {
    const operation = readOperation(body.operation);
    if ((name === "operation_started") !== (operation.status === "running"))
      throw new Error("操作状态无效");
    return { type: name, operation };
  }
  if (
    name === "completed" &&
    (body.outcome === "completed" ||
      body.outcome === "failed" ||
      body.outcome === "interrupted")
  ) {
    const assistantMessage = readMessage(body.assistant_message);
    if (assistantMessage.role !== "assistant")
      throw new Error("对话事件格式无效");
    return {
      type: "completed",
      assistant_message: assistantMessage,
      outcome: body.outcome,
    };
  }
  if (name === "error" && typeof body.code === "string")
    return { type: "error", code: body.code };
  throw new Error("对话事件格式无效");
}

/** 逐块解析 SSE，只有收到持久化终态才算成功；流结束或畸形事件抛错。 */
export async function consumeConversationStream(
  response: Response,
  onEvent: (event: ConversationStreamEvent) => void,
): Promise<void> {
  if (
    !response.body ||
    !response.headers.get("Content-Type")?.includes("text/event-stream")
  )
    throw new Error("对话事件流不可用");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  let acceptedConversationId: string | null = null;
  let acceptedTurnId: string | null = null;
  let eventName = "";
  let dataLines: string[] = [];

  function consumeLine(line: string): void {
    const clean = line.endsWith("\r") ? line.slice(0, -1) : line;
    if (clean === "") {
      if (!eventName && dataLines.length === 0) return;
      const event = readEvent(eventName, dataLines.join("\n"));
      if (terminal) throw new Error("对话终态重复");
      if (event.type === "accepted") {
        if (acceptedConversationId !== null)
          throw new Error("对话确认事件重复");
        acceptedConversationId = event.conversation_id;
        acceptedTurnId = event.turn_id ?? null;
      } else if (acceptedConversationId === null) {
        throw new Error("对话尚未确认保存");
      }
      if (
        (event.type === "operation_started" ||
          event.type === "operation_finished") &&
        event.operation.turn_id !== acceptedTurnId
      )
        throw new Error("执行记录所属轮次无效");
      if (
        event.type === "completed" &&
        event.assistant_message.conversation_id !== acceptedConversationId
      )
        throw new Error("回复所属对话无效");
      onEvent(event);
      eventName = "";
      dataLines = [];
      if (event.type === "completed") terminal = true;
      if (event.type === "error") throw new Error("对话回复保存失败");
      return;
    }
    if (clean.startsWith("event:")) eventName = clean.slice(6).trim();
    if (clean.startsWith("data:")) dataLines.push(clean.slice(5).trimStart());
  }

  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      while (buffer.includes("\n")) {
        const index = buffer.indexOf("\n");
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 1);
        consumeLine(line);
      }
    }
    buffer += decoder.decode();
    if (buffer) consumeLine(buffer);
    if (eventName || dataLines.length) consumeLine("");
    if (!terminal) throw new Error("对话回复未完成");
  } finally {
    reader.releaseLock();
  }
}

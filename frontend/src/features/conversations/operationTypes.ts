/** 用途：执行记录网络契约及边界解析；不推测模型隐藏思考。 */
export type OperationStatus =
  "running" | "completed" | "failed" | "interrupted";
export type SourceReference = {
  source_id: string;
  chunk_id: string;
  title: string;
  section_path: string;
  version: string;
};
export type Citation = SourceReference & { text: string; source_path: string };
export type RouteContribution = {
  route: "vector" | "bm25";
  rank: number;
  score: number;
};
export type RagOperationDetail = {
  kind: "rag";
  query: string;
  candidates: {
    rank: number;
    distance: number | null;
    contributions?: RouteContribution[];
    fusion_score?: number | null;
    preview_truncated?: boolean;
    preview_original_chars?: number;
    reason: string;
    source_id: string | null;
    chunk: {
      chunk_id: string;
      title: string;
      text: string;
      section_path: string;
      version: string;
    };
  }[];
  injected_context: string;
  manifest: Record<string, unknown>;
  distance_filter: string;
  retrieval_mode?: "vector" | "bm25" | "hybrid";
  retrieval_signature?: string;
  route_timings_ms?: Record<string, number>;
};
export type ToolOperationDetail = {
  kind: "tool" | "context";
  arguments: Record<string, unknown>;
  result: unknown;
  error_code?: string;
};
export type TaskSummary = {
  task_id: string;
  intent:
    | "GENERAL_CHAT"
    | "KNOWLEDGE_QA"
    | "REQUIREMENT_ASSESSMENT"
    | "OWN_ORDER_LOOKUP"
    | "OWN_AFTER_SALES_LOOKUP"
    | "ORDER_APPLICATION"
    | "AFTER_SALES_APPLICATION"
    | "NEEDS_CLARIFICATION"
    | "UNSUPPORTED_ACTION";
  capability:
    | "rag_search"
    | "assess_odm_requirements"
    | "list_my_orders"
    | "get_my_order"
    | "list_my_after_sales"
    | "get_my_after_sales"
    | "prepare_order_application"
    | "prepare_after_sales_application"
    | null;
  status:
    | "pending"
    | "running"
    | "completed"
    | "needs_input"
    | "waiting_confirmation"
    | "failed"
    | "blocked";
  error_code: string | null;
};
export type WorkflowOperationDetail = { kind: "workflow"; error_code?: string };
export type OperationSummary = {
  schema_version: 1;
  operation_id: string;
  turn_id: string;
  sequence: number;
  descriptor:
    | { kind: "rag"; name: "rag_search" }
    | {
        kind: "tool";
        name:
          | "assess_odm_requirements"
          | "list_my_orders"
          | "get_my_order"
          | "list_my_after_sales"
          | "get_my_after_sales"
          | "prepare_order_application"
          | "prepare_after_sales_application";
      }
    | { kind: "workflow"; name: "plan_tasks" | "finalize_tasks" }
    | { kind: "context"; name: "summarize_context" | "prepare_profile" };
  status: OperationStatus;
  summary: string;
  elapsed_ms: number | null;
  sources: SourceReference[];
  error_code?: string;
  details?: RagOperationDetail | ToolOperationDetail | WorkflowOperationDetail;
  tasks?: TaskSummary[];
  stop_reason?: string | null;
  task_id?: string | null;
  attempt?: number;
};

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 验证安全任务状态，不从模型正文拼凑任务完成。 */
function readTasks(value: unknown): TaskSummary[] {
  if (!Array.isArray(value) || value.length > 4)
    throw new Error("任务快照无效");
  const rows = value.map((item): TaskSummary => {
    if (
      !isRecord(item) ||
      typeof item.task_id !== "string" ||
      !item.task_id ||
      ![
        "GENERAL_CHAT",
        "KNOWLEDGE_QA",
        "REQUIREMENT_ASSESSMENT",
        "OWN_ORDER_LOOKUP",
        "OWN_AFTER_SALES_LOOKUP",
        "ORDER_APPLICATION",
        "AFTER_SALES_APPLICATION",
        "NEEDS_CLARIFICATION",
        "UNSUPPORTED_ACTION",
      ].includes(String(item.intent)) ||
      !(
        item.capability === null ||
        [
          "rag_search",
          "assess_odm_requirements",
          "list_my_orders",
          "get_my_order",
          "list_my_after_sales",
          "get_my_after_sales",
          "prepare_order_application",
          "prepare_after_sales_application",
        ].includes(String(item.capability))
      ) ||
      ![
        "pending",
        "running",
        "completed",
        "needs_input",
        "waiting_confirmation",
        "failed",
        "blocked",
      ].includes(String(item.status)) ||
      !(item.error_code === null || typeof item.error_code === "string")
    )
      throw new Error("任务快照无效");
    return {
      task_id: item.task_id,
      intent: item.intent as TaskSummary["intent"],
      capability: item.capability as TaskSummary["capability"],
      status: item.status as TaskSummary["status"],
      error_code: item.error_code,
    };
  });
  if (new Set(rows.map((item) => item.task_id)).size !== rows.length)
    throw new Error("重复任务");
  return rows;
}

/** 校验各路原始排名/分数；旧记录没有时保持空，不补造命中。 */
function readContributions(value: unknown): RouteContribution[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("召回路格式无效");
  const rows = value.map((item): RouteContribution => {
    if (
      !isRecord(item) ||
      !["vector", "bm25"].includes(String(item.route)) ||
      !Number.isSafeInteger(item.rank) ||
      Number(item.rank) < 1 ||
      typeof item.score !== "number" ||
      !Number.isFinite(item.score)
    )
      throw new Error("召回路格式无效");
    return {
      route: item.route as RouteContribution["route"],
      rank: Number(item.rank),
      score: item.score,
    };
  });
  if (new Set(rows.map((item) => item.route)).size !== rows.length)
    throw new Error("重复召回路");
  return rows;
}

/** 拒绝未知路、负数或非有限耗时，不把缺失历史数据显示成0。 */
function readTimings(value: unknown): Record<string, number> {
  if (value === undefined) return {};
  if (!isRecord(value)) throw new Error("检索耗时无效");
  const result: Record<string, number> = {};
  for (const [key, milliseconds] of Object.entries(value)) {
    if (
      !["vector", "bm25", "fusion"].includes(key) ||
      typeof milliseconds !== "number" ||
      !Number.isFinite(milliseconds) ||
      milliseconds < 0
    )
      throw new Error("检索耗时无效");
    result[key] = milliseconds;
  }
  return result;
}

/** 校验公开来源字段，不接受模型提供的链接。 */
export function readSource(value: unknown): SourceReference {
  if (
    !isRecord(value) ||
    !["source_id", "chunk_id", "title", "section_path", "version"].every(
      (key) => typeof value[key] === "string",
    )
  )
    throw new Error("来源格式无效");
  return {
    source_id: String(value.source_id),
    chunk_id: String(value.chunk_id),
    title: String(value.title),
    section_path: String(value.section_path),
    version: String(value.version),
  };
}

/** 校验外部快照结构，旧消息没有此字段时由消息解析器保留为空。 */
export function readOperation(value: unknown): OperationSummary {
  if (
    !isRecord(value) ||
    value.schema_version !== 1 ||
    typeof value.operation_id !== "string" ||
    typeof value.turn_id !== "string" ||
    !Number.isSafeInteger(value.sequence) ||
    Number(value.sequence) < 1 ||
    !isRecord(value.descriptor) ||
    typeof value.summary !== "string" ||
    !["running", "completed", "failed", "interrupted"].includes(
      String(value.status),
    ) ||
    !(
      value.elapsed_ms === null ||
      (typeof value.elapsed_ms === "number" &&
        Number.isFinite(value.elapsed_ms) &&
        value.elapsed_ms >= 0)
    ) ||
    !Array.isArray(value.sources)
  )
    throw new Error("执行记录格式无效");
  const kind = value.descriptor.kind;
  if (!(
    (kind === "rag" && value.descriptor.name === "rag_search") ||
    (kind === "tool" &&
      [
        "assess_odm_requirements",
        "list_my_orders",
        "get_my_order",
        "list_my_after_sales",
        "get_my_after_sales",
        "prepare_order_application",
        "prepare_after_sales_application",
      ].includes(String(value.descriptor.name))) ||
    (kind === "workflow" &&
      ["plan_tasks", "finalize_tasks"].includes(
        String(value.descriptor.name),
      )) ||
    (kind === "context" &&
      (value.descriptor.name === "summarize_context" ||
        value.descriptor.name === "prepare_profile"))
  ))
    throw new Error("操作描述无效");
  const record: OperationSummary = {
    schema_version: 1,
    operation_id: value.operation_id,
    turn_id: value.turn_id,
    sequence: Number(value.sequence),
    descriptor:
      kind === "rag"
        ? { kind, name: "rag_search" }
        : kind === "context"
          ? {
              kind,
              name: value.descriptor.name as
                "summarize_context" | "prepare_profile",
            }
          : (value.descriptor as OperationSummary["descriptor"]),
    status: value.status as OperationStatus,
    summary: value.summary,
    elapsed_ms: value.elapsed_ms,
    sources: value.sources.map(readSource),
    ...(typeof value.error_code === "string"
      ? { error_code: value.error_code }
      : {}),
  };
  if (value.tasks !== undefined) record.tasks = readTasks(value.tasks);
  if (value.stop_reason !== undefined) {
    if (!(
      value.stop_reason === null ||
      [
        "all_terminal",
        "awaiting_confirmation",
        "no_progress",
        "needs_input",
        "budget_exhausted",
        "deadline",
        "disconnected",
        "invalid_plan",
      ].includes(String(value.stop_reason))
    ))
      throw new Error("停止原因无效");
    record.stop_reason = value.stop_reason as string | null;
  }
  if (value.task_id !== undefined) {
    if (!(value.task_id === null || typeof value.task_id === "string"))
      throw new Error("任务ID无效");
    record.task_id = value.task_id;
  }
  if (value.attempt !== undefined) {
    if (value.attempt !== 1 && value.attempt !== 2)
      throw new Error("尝试数无效");
    record.attempt = value.attempt;
  }
  if (value.details !== undefined) {
    const details = value.details;
    if (!isRecord(details)) throw new Error("执行详情格式无效");
    if (kind === "workflow") {
      record.details = {
        kind: "workflow",
        ...(typeof details.error_code === "string"
          ? { error_code: details.error_code }
          : {}),
      };
    } else if (kind === "rag") {
      if (typeof details.query !== "string")
        throw new Error("检索详情格式无效");
      const candidates = details.candidates ?? [];
      if (!Array.isArray(candidates)) throw new Error("候选格式无效");
      const mode = details.retrieval_mode ?? "vector";
      if (mode !== "vector" && mode !== "bm25" && mode !== "hybrid")
        throw new Error("检索模式无效");
      const timings = readTimings(details.route_timings_ms);
      record.details = {
        kind: "rag",
        query: details.query,
        candidates: candidates.map((item) => {
          if (
            !isRecord(item) ||
            !Number.isSafeInteger(item.rank) ||
            Number(item.rank) < 1 ||
            !(
              (typeof item.distance === "number" &&
                Number.isFinite(item.distance)) ||
              (mode !== "vector" && item.distance === null)
            ) ||
            typeof item.reason !== "string" ||
            !isRecord(item.chunk)
          )
            throw new Error("候选格式无效");
          const contributions = readContributions(item.contributions);
          if (
            item.distance === null &&
            !contributions.some((row) => row.route === "bm25")
          )
            throw new Error("词法独有候选缺少贡献");
          const fusionScore = item.fusion_score ?? null;
          if (
            fusionScore !== null &&
            (typeof fusionScore !== "number" ||
              !Number.isFinite(fusionScore) ||
              fusionScore < 0)
          )
            throw new Error("融合分数无效");
          const chunk = item.chunk;
          if (
            !["chunk_id", "title", "text", "section_path", "version"].every(
              (key) => typeof chunk[key] === "string",
            )
          )
            throw new Error("候选格式无效");
          const previewTruncated = item.preview_truncated ?? false;
          const previewLength =
            item.preview_original_chars ??
            Array.from(String(chunk.text)).length;
          if (
            typeof previewTruncated !== "boolean" ||
            !Number.isSafeInteger(previewLength) ||
            Number(previewLength) < Array.from(String(chunk.text)).length ||
            (previewTruncated && item.preview_original_chars === undefined)
          )
            throw new Error("候选预览标记无效");
          return {
            rank: Number(item.rank),
            distance: item.distance as number | null,
            contributions,
            fusion_score: fusionScore as number | null,
            preview_truncated: previewTruncated,
            preview_original_chars: Number(previewLength),
            reason: item.reason,
            source_id:
              typeof item.source_id === "string" ? item.source_id : null,
            chunk: {
              chunk_id: String(item.chunk.chunk_id),
              title: String(item.chunk.title),
              text: String(item.chunk.text),
              section_path: String(item.chunk.section_path),
              version: String(item.chunk.version),
            },
          };
        }),
        injected_context:
          typeof details.injected_context === "string"
            ? details.injected_context
            : "",
        manifest: isRecord(details.manifest) ? details.manifest : {},
        distance_filter:
          typeof details.distance_filter === "string"
            ? details.distance_filter
            : "disabled",
        retrieval_mode: mode,
        retrieval_signature:
          typeof details.retrieval_signature === "string"
            ? details.retrieval_signature
            : "vector-cosine-v1（旧记录）",
        route_timings_ms: timings,
      };
    } else {
      if (!isRecord(details.arguments)) throw new Error("工具详情格式无效");
      record.details = {
        kind: kind === "context" ? "context" : "tool",
        arguments: details.arguments,
        result: details.result ?? null,
        ...(typeof details.error_code === "string"
          ? { error_code: details.error_code }
          : {}),
      };
    }
  }
  return record;
}

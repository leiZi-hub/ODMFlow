/** 用途：实时/历史共用执行记录折叠面板；详情仅按服务器权限按需读取。 */
import { useEffect, useRef, useState, type ReactElement } from "react";
import { listTurnOperations } from "./conversationApi";
import type { OperationSummary } from "./operationTypes";

type Props = {
  conversationId: string;
  turnId: string;
  operations: OperationSummary[];
  detailsAvailable: boolean;
};
const labels = {
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
};
const reasons: Record<string, string> = {
  selected: "已注入",
  duplicate: "重复排除",
  context_budget: "超出上下文预算",
  distance: "超出距离阈值",
  rank_budget: "超出最终片段数预算",
};
const routeLabels: Record<string, string> = {
  vector: "向量",
  bm25: "BM25",
  fusion: "融合",
};
const modeLabels = {
  vector: "向量召回",
  bm25: "BM25词法召回",
  hybrid: "混合召回（向量＋BM25，RRF）",
};
const taskLabels = {
  pending: "待执行",
  running: "执行中",
  completed: "完成",
  needs_input: "需补信息",
  waiting_confirmation: "等待用户确认",
  failed: "失败",
  blocked: "依赖阻塞",
};
const intentLabels = {
  GENERAL_CHAT: "普通交流",
  KNOWLEDGE_QA: "资料查询",
  REQUIREMENT_ASSESSMENT: "需求评估",
  OWN_ORDER_LOOKUP: "本人订单查询",
  OWN_AFTER_SALES_LOOKUP: "本人售后查询",
  ORDER_APPLICATION: "准备模拟订单申请",
  AFTER_SALES_APPLICATION: "准备模拟售后申请",
  NEEDS_CLARIFICATION: "需要澄清",
  UNSUPPORTED_ACTION: "暂不支持的操作",
};
const stopLabels: Record<string, string> = {
  all_terminal: "本轮任务已终结",
  awaiting_confirmation: "申请已准备，等待用户确认",
  no_progress: "没有可继续的进展",
  needs_input: "需要补充信息",
  budget_exhausted: "达到本轮调用上限",
  deadline: "达到本轮等待上限",
  disconnected: "连接中断",
  invalid_plan: "任务计划未通过检查",
};

/** 同一轮一份面板，操作ID稳定；取消/迟到响应不污染其他会话。 */
export function TurnExecutionPanel({
  conversationId,
  turnId,
  operations,
  detailsAvailable,
}: Props): ReactElement | null {
  const [loaded, setLoaded] = useState<{
    key: string;
    items: OperationSummary[];
  } | null>(null);
  const [error, setError] = useState("");
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const key = `${conversationId}/${turnId}`;
  const loading = loadingKey === key;
  const version = useRef(0);
  useEffect(() => {
    const generation = ++version.current;
    return () => {
      version.current = generation + 1;
      active.current?.abort();
    };
  }, [key]);

  async function expand(): Promise<void> {
    if (
      !detailsAvailable ||
      loading ||
      loaded?.key === key ||
      operations.every((item) => item.details)
    )
      return;
    const current = version.current;
    const abort = new AbortController();
    active.current = abort;
    setLoadingKey(key);
    setError("");
    try {
      const page = await listTurnOperations(
        conversationId,
        turnId,
        abort.signal,
      );
      if (current !== version.current || abort.signal.aborted) return;
      setLoaded({ key, items: page.items });
    } catch {
      if (current === version.current && !abort.signal.aborted)
        setError("详细记录加载失败，可重新展开查看。");
    } finally {
      if (current === version.current) setLoadingKey(null);
    }
  }

  if (!operations.length) return null;
  const rows = operations
    .map((item) => {
      const saved =
        loaded?.key === key
          ? loaded.items.find((row) => row.operation_id === item.operation_id)
          : undefined;
      return saved?.details && saved.status === item.status ? saved : item;
    })
    .sort((left, right) => left.sequence - right.sequence);
  return (
    <section className="turn-execution" aria-label="本轮执行记录">
      {rows.map((item) => (
        <details
          className="execution-row"
          key={item.operation_id}
          onToggle={(event) => {
            if (event.currentTarget.open) void expand();
          }}
        >
          <summary>
            <span aria-hidden="true">
              {item.descriptor.kind === "rag" ? "⌕" : "⚙"}
            </span>{" "}
            {item.summary} · {labels[item.status]}{" "}
            {item.elapsed_ms !== null && `· ${item.elapsed_ms} ms`}
          </summary>
          <div className="execution-detail">
            {item.tasks?.map((task) => (
              <p key={task.task_id}>
                {intentLabels[task.intent]} · {taskLabels[task.status]}
                {task.error_code && ` · ${task.error_code}`}
              </p>
            ))}
            {item.stop_reason && (
              <p>
                停止原因：{stopLabels[item.stop_reason] ?? item.stop_reason}
              </p>
            )}
            {item.attempt && <p>实际尝试：第 {item.attempt} 次</p>}
            {item.error_code && <p>错误类别：{item.error_code}</p>}
            {item.sources.map((source) => (
              <p key={source.source_id}>
                [{source.source_id}] {source.title} / {source.section_path} ·{" "}
                版本 {source.version}
              </p>
            ))}
            {!detailsAvailable && <p>调试详情未开启；仅显示执行摘要和来源。</p>}
            {detailsAvailable && loading && <p>正在读取已保存记录…</p>}
            {detailsAvailable && error && <p role="alert">{error}</p>}
            {item.details?.kind === "rag" && (
              <>
                <p>检索问题：{item.details.query}</p>
                <p>
                  模式：{modeLabels[item.details.retrieval_mode ?? "vector"]}
                </p>
                <p>
                  评分含义：cosine距离越小越近；BM25/RRF越大排名越靠前，均非答案置信度。
                </p>
                {Object.entries(item.details.route_timings_ms ?? {}).map(
                  ([route, milliseconds]) => (
                    <p key={route}>
                      {routeLabels[route] ?? route}耗时：
                      {milliseconds.toFixed(2)} ms
                    </p>
                  ),
                )}
                <p>
                  距离筛选：
                  {item.details.distance_filter === "enabled"
                    ? "已启用"
                    : "未标定；距离不是置信度"}
                </p>
                <details>
                  <summary>索引与模型签名</summary>
                  <p>
                    检索签名：{item.details.retrieval_signature ?? "旧向量记录"}
                  </p>
                  <pre>{JSON.stringify(item.details.manifest, null, 2)}</pre>
                </details>
                {item.details.candidates.length === 0 && (
                  <p>没有候选片段或检索尚未完成。</p>
                )}
                {item.details.candidates.map((candidate) => (
                  <details
                    key={`${candidate.rank}-${candidate.chunk.chunk_id}`}
                  >
                    <summary>
                      #{candidate.rank} {candidate.chunk.title} · 向量距离：
                      {candidate.distance === null
                        ? "无（仅词法命中）"
                        : candidate.distance.toFixed(4)}
                      {candidate.fusion_score != null &&
                        ` · RRF ${candidate.fusion_score.toFixed(5)}`}{" "}
                      · {reasons[candidate.reason] ?? candidate.reason}
                    </summary>
                    <p>
                      {candidate.chunk.section_path} · 版本{" "}
                      {candidate.chunk.version} · {candidate.chunk.chunk_id}
                    </p>
                    {(candidate.contributions ?? []).map((route) => (
                      <p key={route.route}>
                        {routeLabels[route.route]} · 原排名 #{route.rank} ·
                        原始分数 {route.score.toFixed(4)}
                      </p>
                    ))}
                    <pre>{candidate.chunk.text}</pre>
                    {candidate.preview_truncated && (
                      <p>
                        候选正文仅显示预览（原文{" "}
                        {candidate.preview_original_chars}{" "}
                        字符）；实际注入与可信来源未截断。
                      </p>
                    )}
                  </details>
                ))}
                <details>
                  <summary>实际送入 LLM 的片段</summary>
                  <pre>{item.details.injected_context || "无选用片段"}</pre>
                </details>
              </>
            )}
            {(item.details?.kind === "tool" ||
              item.details?.kind === "context") && (
              <>
                <p>
                  {item.details.kind === "context" ? "上下文整理" : "工具"}：
                  {item.descriptor.name}
                </p>
                <pre>
                  {JSON.stringify(
                    {
                      arguments: item.details.arguments,
                      result: item.details.result,
                    },
                    null,
                    2,
                  )}
                </pre>
              </>
            )}
          </div>
        </details>
      ))}
    </section>
  );
}

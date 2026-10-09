/** 用途：呈现私人持久对话；边界：服务端 MySQL 是消息权威，组件只保存界面临时状态。 */
import { BusinessActionPanel } from "../actions/BusinessActionPanel";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
  type ReactNode,
} from "react";

import { ApiError } from "../../shared/api/http";
import {
  listConversations,
  listMessages,
  sendConversationTurn,
  type Conversation,
} from "./conversationApi";
import type {
  ConversationMessage,
  ConversationStreamEvent,
} from "./streamEvents";
import { TurnExecutionPanel } from "./TurnExecutionPanel";
import type { OperationSummary } from "./operationTypes";

export type ConversationWorkspaceProps = { onUnauthorized(): void };

/** 组合私人对话列表、历史、发送和流式回复；所有保存状态由后端事件确认。 */
export function ConversationWorkspace({
  onUnauthorized,
}: ConversationWorkspaceProps): ReactElement {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [hasMoreConversations, setHasMoreConversations] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [optimistic, setOptimistic] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [operations, setOperations] = useState<OperationSummary[]>([]);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [detailsAvailable, setDetailsAvailable] = useState(false);
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const selectionVersion = useRef(0);

  useEffect(() => {
    let mounted = true;
    async function loadInitial(): Promise<void> {
      try {
        const page = await listConversations();
        if (!mounted) return;
        setConversations(page.items);
        setHasMoreConversations(page.has_more);
        if (page.items[0]) {
          const id = page.items[0].id;
          const history = await listMessages(id);
          if (!mounted) return;
          setSelectedId(id);
          setMessages(history.items);
          setNextBeforeId(history.next_before_id);
        }
      } catch (cause) {
        if (!mounted) return;
        if (cause instanceof ApiError && cause.status === 401) onUnauthorized();
        else setError("暂时无法加载对话，请检查服务后刷新页面。");
      } finally {
        if (mounted) setLoading(false);
      }
    }
    void loadInitial();
    return () => {
      mounted = false;
      abortRef.current?.abort();
    };
  }, [onUnauthorized]);

  async function refreshList(): Promise<void> {
    try {
      const page = await listConversations();
      setConversations(page.items);
      setHasMoreConversations(page.has_more);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onUnauthorized();
      else setError("对话列表刷新失败，请稍后再试。");
    }
  }

  async function openConversation(id: string): Promise<void> {
    if (sendingRef.current || id === selectedId) return;
    const version = ++selectionVersion.current;
    setSelectedId(id);
    setMessages([]);
    setOperations([]);
    setActiveTurnId(null);
    setNextBeforeId(null);
    setError("");
    try {
      const history = await listMessages(id);
      if (version !== selectionVersion.current) return;
      setMessages(history.items);
      setNextBeforeId(history.next_before_id);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onUnauthorized();
      else setError("历史消息加载失败，请重新选择对话。");
    }
  }

  async function loadOlder(): Promise<void> {
    if (!selectedId || nextBeforeId === null) return;
    try {
      const history = await listMessages(selectedId, 30, nextBeforeId);
      setMessages((current) => [
        ...history.items.filter(
          (item) => !current.some((saved) => saved.id === item.id),
        ),
        ...current,
      ]);
      setNextBeforeId(history.next_before_id);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onUnauthorized();
      else setError("更早消息加载失败，请稍后再试。");
    }
  }

  async function loadMoreConversations(): Promise<void> {
    try {
      const page = await listConversations(30, conversations.length);
      setConversations((current) => [...current, ...page.items]);
      setHasMoreConversations(page.has_more);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onUnauthorized();
      else setError("更多对话加载失败，请稍后再试。");
    }
  }

  function beginNew(): void {
    if (sendingRef.current) return;
    ++selectionVersion.current;
    setSelectedId(null);
    setMessages([]);
    setOperations([]);
    setActiveTurnId(null);
    setNextBeforeId(null);
    setOptimistic(null);
    setStreamText("");
    setOperations([]);
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const question = draft.trim();
    if (!question || question.length > 4000 || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setAccepted(false);
    setOptimistic(question);
    setDraft("");
    setStreamText("");
    setOperations([]);
    setActiveTurnId(null);
    setError("");
    const abort = new AbortController();
    abortRef.current = abort;
    let userSaved = false;
    const runOperations = new Map<string, OperationSummary>();
    try {
      const input = {
        message: question,
        client_turn_id: crypto.randomUUID(),
        ...(selectedId ? { conversation_id: selectedId } : {}),
      };
      await sendConversationTurn(
        input,
        (streamEvent: ConversationStreamEvent) => {
          if (streamEvent.type === "accepted") {
            userSaved = true;
            setAccepted(true);
            setOptimistic(null);
            setSelectedId(streamEvent.conversation_id);
            setActiveTurnId(streamEvent.turn_id ?? null);
            setDetailsAvailable(streamEvent.details_available ?? false);
            setMessages((current) => [...current, streamEvent.user_message]);
          } else if (streamEvent.type === "token") {
            setStreamText((current) => current + streamEvent.text);
          } else if (
            streamEvent.type === "operation_started" ||
            streamEvent.type === "operation_finished"
          ) {
            runOperations.set(
              streamEvent.operation.operation_id,
              streamEvent.operation,
            );
            setOperations([...runOperations.values()]);
            setMessages((current) =>
              current.map((item) =>
                item.role === "user" &&
                item.turn_id === streamEvent.operation.turn_id
                  ? { ...item, operations: [...runOperations.values()] }
                  : item,
              ),
            );
          } else if (streamEvent.type === "completed") {
            setMessages((current) => [
              ...current,
              {
                ...streamEvent.assistant_message,
                operations: streamEvent.assistant_message.operations ?? [
                  ...runOperations.values(),
                ],
              },
            ]);
            setStreamText("");
            setOperations([]);
            setActiveTurnId(null);
          }
        },
        abort.signal,
      );
      await refreshList();
    } catch (cause) {
      setActiveTurnId(null);
      if (cause instanceof ApiError && cause.status === 401) {
        onUnauthorized();
        return;
      }
      setStreamText("");
      if (!userSaved) {
        setOptimistic(null);
        setDraft(question);
        setError("发送状态未确认，请先查看对话列表；原文已保留在输入框。");
      } else {
        setError("本轮回复未确认保存，请刷新页面查看最终状态。");
        await refreshList();
      }
    } finally {
      abortRef.current = null;
      sendingRef.current = false;
      setSending(false);
    }
  }

  /** 卡片依附原turn：优先助手回复；断流无回复则留在该轮用户消息下方。 */
  function renderMessages(
    renderTurnActions: (turnId: string) => ReactNode,
    controls: ReactNode = null,
  ): ReactElement {
    return (
      <>
        {messages.map((item) =>
          item.role === "user" ? (
            <div key={item.id}>
              <p className="agent-user-message">{item.content}</p>
              {item.turn_id &&
                item.turn_id !== activeTurnId &&
                !messages.some(
                  (saved) =>
                    saved.role === "assistant" &&
                    saved.turn_id === item.turn_id,
                ) && (
                  <>
                    <TurnExecutionPanel
                      conversationId={item.conversation_id}
                      turnId={item.turn_id}
                      operations={item.operations ?? []}
                      detailsAvailable={item.details_available ?? false}
                    />
                    {renderTurnActions(item.turn_id)}
                  </>
                )}
            </div>
          ) : (
            <div className="agent-reply" key={item.id}>
              <span className="agent-avatar" aria-hidden="true">
                O
              </span>
              <div>
                {item.turn_id && (
                  <TurnExecutionPanel
                    conversationId={item.conversation_id}
                    turnId={item.turn_id}
                    operations={item.operations ?? []}
                    detailsAvailable={item.details_available ?? false}
                  />
                )}
                <p>
                  {item.content}
                  {item.kind === "fallback" && (
                    <span className="conversation-state"> · 未完成</span>
                  )}
                </p>
                {item.citations?.map((source) => (
                  <details className="citation-source" key={source.source_id}>
                    <summary>
                      [{source.source_id}] {source.title} ·{" "}
                      {source.section_path} · {source.version}
                    </summary>
                    <pre>{source.text}</pre>
                  </details>
                ))}
                {item.turn_id && renderTurnActions(item.turn_id)}
              </div>
            </div>
          ),
        )}
        {optimistic !== null && (
          <div className="agent-user-message conversation-optimistic">
            <p>{optimistic}</p>
            <span className="conversation-state">发送中</span>
          </div>
        )}
        {sending &&
          accepted &&
          (!activeTurnId ||
            !messages.some(
              (item) =>
                item.role === "assistant" && item.turn_id === activeTurnId,
            )) && (
            <div className="agent-reply" role="status">
              <span className="agent-avatar" aria-hidden="true">
                O
              </span>
              <div>
                {selectedId && activeTurnId && (
                  <TurnExecutionPanel
                    conversationId={selectedId}
                    turnId={activeTurnId}
                    operations={operations}
                    detailsAvailable={detailsAvailable}
                  />
                )}
                <p>{streamText || "Agent 正在思考…"}</p>
                <span className="conversation-state">生成中</span>
                {activeTurnId && renderTurnActions(activeTurnId)}
              </div>
            </div>
          )}
        {controls}
      </>
    );
  }

  return (
    <div className="conversation-layout">
      <aside className="conversation-list" aria-label="私人对话列表">
        <button
          type="button"
          className="conversation-new"
          disabled={sending}
          onClick={beginNew}
        >
          新对话
        </button>
        {loading && <p role="status">正在加载对话…</p>}
        {conversations.map((item) => (
          <button
            type="button"
            key={item.id}
            className={
              item.id === selectedId
                ? "conversation-item selected"
                : "conversation-item"
            }
            disabled={sending}
            onClick={() => void openConversation(item.id)}
          >
            {item.title}
          </button>
        ))}
        {hasMoreConversations && (
          <button
            type="button"
            className="conversation-more"
            onClick={() => void loadMoreConversations()}
          >
            更多对话
          </button>
        )}
      </aside>
      <section className="agent-conversation" aria-label="Agent 对话">
        <div className="agent-scroll" aria-live="polite">
          {nextBeforeId !== null && (
            <button
              type="button"
              className="conversation-more"
              onClick={() => void loadOlder()}
            >
              加载更早消息
            </button>
          )}
          {messages.length === 0 &&
            optimistic === null &&
            !sending &&
            !loading && (
              <div className="conversation-empty">
                <span className="empty-symbol" aria-hidden="true">
                  ✳
                </span>
                <p className="eyebrow">ODMFlow · AGENT WORKSPACE</p>
                <h1>从一个问题开始</h1>
                <p>私人对话会保存到 MySQL；可以咨询 Android ODM 需求。</p>
              </div>
            )}
          {selectedId ? (
            <BusinessActionPanel
              key={selectedId}
              conversationId={selectedId}
              refreshKey={messages.length}
              onUnauthorized={onUnauthorized}
              disabled={sending}
              onQuery={setDraft}
              visibleTurnIds={[
                ...messages.flatMap((item) =>
                  item.turn_id ? [item.turn_id] : [],
                ),
                ...(activeTurnId ? [activeTurnId] : []),
              ]}
            >
              {renderMessages}
            </BusinessActionPanel>
          ) : (
            renderMessages(() => null)
          )}
        </div>
        <div className="agent-composer-wrap">
          {error && (
            <p className="workspace-error" role="alert">
              {error}
            </p>
          )}
          <form
            className="agent-composer"
            onSubmit={(event) => void submit(event)}
          >
            <label htmlFor="conversation-message">消息</label>
            <textarea
              id="conversation-message"
              value={draft}
              maxLength={4000}
              rows={3}
              onChange={(event) => setDraft(event.target.value)}
              disabled={sending}
              placeholder="输入你想咨询的问题…"
            />
            <div className="agent-composer-actions">
              <span>消息提交后保存到 MySQL；生成中文字尚未保存。</span>
              <button
                type="submit"
                disabled={sending || !draft.trim()}
                aria-label="发送消息"
              >
                {sending ? "发送中…" : "发送消息"}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}

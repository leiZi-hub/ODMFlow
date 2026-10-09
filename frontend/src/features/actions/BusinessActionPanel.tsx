/** 用途：本人对话中的模拟确认卡；边界：不判断权限，不重放写请求，不承担业务CRUD。 */
import {
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { ApiError } from "../../shared/api/http";
import {
  decideAction,
  getAction,
  listActions,
  type BusinessAction,
  type ActionPage,
} from "./actionApi";

type Props = {
  conversationId: string;
  refreshKey: number;
  onUnauthorized(): void;
  onQuery?(question: string): void;
  disabled?: boolean;
  visibleTurnIds?: readonly string[];
  /** 由消息时间线指定卡片位置；控制器仍只维护一份会话级网络/确认状态。 */
  children?(
    renderTurnActions: (turnId: string) => ReactElement | null,
    controls: ReactNode,
  ): ReactElement;
};
const states = {
  pending_confirmation: "等待确认 · 尚未提交",
  succeeded: "模拟申请已提交",
  cancelled: "已取消 · 未创建业务",
  expired: "已过期 · 请重新准备",
  invalidated: "条件已变化 · 请重新准备",
};
const fields: Record<string, string> = {
  product_model: "产品型号",
  quantity: "数量",
  target_market: "目标地区",
  configuration_summary: "定制配置",
  order_no: "关联订单",
  symptom: "故障现象",
  occurred_at: "发生时间",
  reproduction: "复现步骤",
  handling: "处理意向",
  device_identifier: "设备标识",
};
const values: Record<string, string> = {
  repair_consultation: "检测/维修咨询",
  exchange_request: "换货申请",
  return_request: "退货申请",
};

/** 生命周期跟随会话/账号；网络未知先GET，后端唯一动作是结果权威。 */
export function BusinessActionPanel({
  conversationId,
  refreshKey,
  onUnauthorized,
  onQuery,
  disabled = false,
  visibleTurnIds,
  children,
}: Props): ReactElement | null {
  const [page, setPage] = useState<ActionPage>({ items: [], has_more: false });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const alive = useRef(false);
  const requests = useRef(new Set<AbortController>());
  const lock = useRef(false);
  const notify = useRef(onUnauthorized);
  const loadedCount = useRef(0);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    notify.current = onUnauthorized;
  }, [onUnauthorized]);
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    async function readLoadedPages(): Promise<ActionPage> {
      let result = await listActions(conversationId, 0, controller.signal);
      // 新消息刷新时保留已展开的申请页，不能只读第一页而丢掉较早卡片。
      while (result.has_more && result.items.length < loadedCount.current) {
        const next = await listActions(
          conversationId,
          result.items.length,
          controller.signal,
        );
        if (!next.items.length) break;
        result = {
          items: [...result.items, ...next.items],
          has_more: next.has_more,
        };
      }
      return result;
    }
    void readLoadedPages()
      .then((result) => {
        loadedCount.current = Math.max(
          loadedCount.current,
          result.items.length,
        );
        if (!controller.signal.aborted)
          setPage((previous) => ({
            ...result,
            items: result.items.map((incoming) => {
              const known = previous.items.find(
                (row) => row.id === incoming.id,
              );
              // GET可能早于确认开始、晚于确认返回；不能用旧pending覆盖真实终态。
              return known &&
                (known.revision > incoming.revision ||
                  (known.revision === incoming.revision &&
                    known.status !== "pending_confirmation" &&
                    incoming.status === "pending_confirmation"))
                ? known
                : incoming;
            }),
          }));
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        if (cause instanceof ApiError && cause.status === 401) notify.current();
        else setError("申请卡暂不可读取，请检查后端及数据库迁移。");
      });
    return () => {
      controller.abort();
    };
  }, [conversationId, refreshKey]);
  useEffect(
    () => () => {
      alive.current = false;
      requests.current.forEach((controller) => controller.abort());
    },
    [],
  );

  /** 只替换服务端已返回快照，不能推测POST失败等于未提交。 */
  function replaceAction(result: BusinessAction): void {
    if (result.conversation_id !== conversationId) throw new ApiError(null);
    setPage((previous) => ({
      ...previous,
      items: previous.items.map((row) => (row.id === result.id ? result : row)),
    }));
  }

  /** CSRF确认失败或网络未知均先读同ID状态；没有自动写重试。 */
  async function decide(
    action: BusinessAction,
    confirmed: boolean,
  ): Promise<void> {
    if (lock.current || disabled) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const controller = new AbortController();
    requests.current.add(controller);
    try {
      const result = await decideAction(action, confirmed, controller.signal);
      if (alive.current) {
        replaceAction(result);
        setUncertain(null);
      }
    } catch (cause) {
      if (!alive.current) return;
      if (cause instanceof ApiError && cause.status === 401) {
        notify.current();
        return;
      }
      setUncertain(action.id);
      try {
        const actual = await getAction(action.id, controller.signal);
        if (alive.current) {
          replaceAction(actual);
          setUncertain(
            actual.status === "pending_confirmation" ? actual.id : null,
          );
          setError(
            actual.status === "pending_confirmation"
              ? "结果尚未确认，先重新读取状态；不要连续提交。"
              : "",
          );
        }
      } catch (readError) {
        if (!alive.current) return;
        if (readError instanceof ApiError && readError.status === 401)
          notify.current();
        else setError("结果暂时不明。请重新读取申请状态，不要重复提交。");
      }
    } finally {
      requests.current.delete(controller);
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }

  /** 用户显式读取未知结果；读取失败继续保留提交锁。 */
  async function reload(): Promise<void> {
    if (!uncertain || lock.current) return;
    const controller = new AbortController();
    requests.current.add(controller);
    try {
      const actual = await getAction(uncertain, controller.signal);
      if (alive.current) {
        replaceAction(actual);
        setUncertain(null);
        setError("");
      }
    } catch (cause) {
      if (alive.current && cause instanceof ApiError && cause.status === 401)
        notify.current();
    } finally {
      requests.current.delete(controller);
    }
  }

  /** 稳定分页，只追加当前会话动作，卸载/换号时放弃迟到结果。 */
  async function more(): Promise<void> {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    const controller = new AbortController();
    requests.current.add(controller);
    try {
      const next = await listActions(
        conversationId,
        page.items.length,
        controller.signal,
      );
      if (alive.current) {
        loadedCount.current = Math.max(
          loadedCount.current,
          page.items.length + next.items.length,
        );
        setPage((previous) => ({
          has_more: next.has_more,
          items: [
            ...previous.items,
            ...next.items.filter(
              (row) => !previous.items.some((old) => old.id === row.id),
            ),
          ],
        }));
      }
    } catch (cause) {
      if (alive.current) {
        if (cause instanceof ApiError && cause.status === 401) notify.current();
        else setError("更多申请读取失败。");
      }
    } finally {
      requests.current.delete(controller);
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }

  /** 只呈现指定轮次的卡，不重新查询，不因最新消息而改变业务归属。 */
  function renderCards(items: BusinessAction[]): ReactElement | null {
    if (!items.length) return null;
    return (
      <section className="business-actions" aria-label="本对话模拟申请">
        {items.map((action) => (
          <article className="business-action-card" key={action.id}>
            <header>
              <strong>
                {action.kind === "order_application"
                  ? "模拟订单申请"
                  : "模拟售后申请"}
              </strong>
              <span>
                {action.status === "pending_confirmation" &&
                now >= Date.parse(action.expires_at)
                  ? "已超过确认有效期 · 请重新准备"
                  : states[action.status]}
              </span>
            </header>
            <dl>
              {Object.entries(action.parameters).map(
                ([key, value]) =>
                  value !== null && (
                    <div key={key}>
                      <dt>{fields[key] ?? key}</dt>
                      <dd>{values[String(value)] ?? String(value)}</dd>
                    </div>
                  ),
              )}
            </dl>
            <p className="action-boundary">
              仅为模拟演示，不涉及真实支付、退款或物流。售后受理不代表批准退换。
            </p>
            {action.result && (
              <div>
                <p>
                  编号：<strong>{action.result.business_no}</strong> ·{" "}
                  {action.result.status === "submitted"
                    ? "已受理意向，待审核"
                    : "待审核"}
                </p>
                {onQuery && (
                  <button
                    type="button"
                    disabled={disabled || busy}
                    onClick={() =>
                      onQuery(
                        `查询我的${action.kind === "order_application" ? "订单" : "售后申请"} ${action.result!.business_no} 的进度`,
                      )
                    }
                  >
                    在对话中查询进度
                  </button>
                )}
              </div>
            )}
            {action.status === "pending_confirmation" && (
              <>
                <small>
                  确认有效期至 {new Date(action.expires_at).toLocaleString()}
                </small>
                <div className="action-buttons">
                  <button
                    type="button"
                    disabled={
                      busy ||
                      disabled ||
                      uncertain === action.id ||
                      now >= Date.parse(action.expires_at)
                    }
                    onClick={() => void decide(action, true)}
                  >
                    确认提交模拟申请
                  </button>
                  <button
                    type="button"
                    disabled={busy || disabled || uncertain === action.id}
                    onClick={() => void decide(action, false)}
                  >
                    取消申请
                  </button>
                </div>
              </>
            )}
          </article>
        ))}
      </section>
    );
  }

  const unloaded =
    visibleTurnIds !== undefined &&
    page.items.some((action) => !visibleTurnIds.includes(action.turn_id));
  const controls = (
    <>
      {error && (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      )}
      {uncertain && (
        <button type="button" onClick={() => void reload()}>
          重新读取申请状态
        </button>
      )}
      {unloaded && (
        <p className="conversation-state">
          申请卡属于尚未加载的较早对话，请加载更早消息查看。
        </p>
      )}
      {page.has_more && (
        <button type="button" disabled={busy} onClick={() => void more()}>
          加载更多申请
        </button>
      )}
    </>
  );
  if (children)
    return children(
      (turnId) =>
        renderCards(page.items.filter((action) => action.turn_id === turnId)),
      controls,
    );
  if (!page.items.length && !error) return null;
  return (
    <>
      {renderCards(page.items)}
      {controls}
    </>
  );
}

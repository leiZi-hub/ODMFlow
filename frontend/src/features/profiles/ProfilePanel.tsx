/** 用途：人工查看、修改和删除本人稳定画像；边界：不管理会话摘要或私人经历。 */
import { useEffect, useRef, useState, type ReactElement } from "react";

import { ApiError } from "../../shared/api/http";
import {
  deleteProfile,
  editProfile,
  getProfile,
  profileFields,
  type ProfileField,
  type ProfileSnapshot,
} from "./profileApi";

type Props = { onClose(): void; onUnauthorized(): void };

/** 仅打开时读取画像；卸载后迟到请求不更新界面或切换另一个账号。 */
export function ProfilePanel({ onClose, onUnauthorized }: Props): ReactElement {
  const [snapshot, setSnapshot] = useState<ProfileSnapshot | null>(null);
  const [field, setField] = useState<ProfileField>("language");
  const [value, setValue] = useState("zh-CN");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  const unauthorized = useRef(onUnauthorized);
  useEffect(() => {
    unauthorized.current = onUnauthorized;
  }, [onUnauthorized]);

  useEffect(() => {
    let disposed = false;
    active.current = true;
    void getProfile()
      .then((result) => {
        if (!disposed) setSnapshot(result);
      })
      .catch((cause) => {
        if (disposed) return;
        if (cause instanceof ApiError && cause.status === 401)
          unauthorized.current();
        else setError("画像暂不可读取，请确认数据库迁移和后端服务。");
      });
    return () => {
      disposed = true;
      active.current = false;
    };
  }, []);

  /** 所有写入等待服务端快照成功；错误保持当前编辑，不自动重试。 */
  async function update(
    operation: () => Promise<ProfileSnapshot>,
  ): Promise<void> {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await operation();
      if (active.current) setSnapshot(result);
    } catch (cause) {
      if (!active.current) return;
      if (cause instanceof ApiError && cause.status === 401)
        unauthorized.current();
      else
        setError(
          cause instanceof ApiError && cause.status === 409
            ? "画像已变化，请重新加载后确认再保存；输入已保留。"
            : "操作未完成，请检查字段值或稍后重试。",
        );
    } finally {
      if (active.current) setBusy(false);
    }
  }

  function selectField(next: ProfileField): void {
    setField(next);
    const existing = snapshot?.items.find(
      (item) => item.field_key === next,
    )?.value;
    const options = profileFields[next].values;
    setValue(existing ?? (options ? (Object.keys(options)[0] ?? "") : ""));
  }
  const options = profileFields[field].values;
  return (
    <section className="profile-panel" aria-label="我的画像">
      <div className="profile-panel-heading">
        <h2>我的画像</h2>
        <button type="button" onClick={onClose}>
          关闭画像
        </button>
      </div>
      <p>
        只保留跨会话使用的本人偏好和业务方向，不保存私人经历。人工设置优先于自动提取；删除后暂停自动记录，重新设置可恢复。
      </p>
      {error && <p role="alert">{error}</p>}
      {!snapshot ? (
        <p>正在读取画像…</p>
      ) : (
        <>
          {snapshot.items.length === 0 && (
            <p>
              暂无已保存的画像。可以手动设置，也可在对话中明确表达长期偏好。
            </p>
          )}
          <ul className="profile-items">
            {snapshot.items.map((item) => (
              <li key={item.field_key}>
                <div>
                  <strong>{profileFields[item.field_key].label}</strong>
                  <span>
                    {item.value
                      ? ((
                          profileFields[item.field_key].values as Record<
                            string,
                            string
                          > | null
                        )?.[item.value] ?? item.value)
                      : "已删除，暂停自动记录"}
                  </span>
                  <small>
                    {item.origin === "manual"
                      ? "人工设置"
                      : item.origin === "conversation"
                        ? `来自对话 · 消息 #${item.source_message_id}`
                        : "人工删除"}{" "}
                    · {new Date(item.updated_at).toLocaleString()}
                  </small>
                  {item.source_conversation_id && (
                    <small>来源对话：{item.source_conversation_id}</small>
                  )}
                  {item.evidence && <small>原话证据：{item.evidence}</small>}
                </div>
                <button
                  type="button"
                  onClick={() => selectField(item.field_key)}
                  disabled={busy}
                >
                  编辑{profileFields[item.field_key].label}
                </button>
                {!item.suppressed && (
                  <button
                    type="button"
                    aria-label={`删除${profileFields[item.field_key].label}`}
                    disabled={busy}
                    onClick={() =>
                      void update(() =>
                        deleteProfile(snapshot.revision, item.field_key),
                      )
                    }
                  >
                    删除
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      <form
        className="profile-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (snapshot)
            void update(() => editProfile(snapshot.revision, field, value));
        }}
      >
        <label>
          画像字段
          <select
            value={field}
            disabled={busy}
            onChange={(event) =>
              selectField(event.target.value as ProfileField)
            }
          >
            {Object.entries(profileFields).map(([key, spec]) => (
              <option key={key} value={key}>
                {spec.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          画像值
          {options ? (
            <select
              value={value}
              disabled={busy}
              onChange={(event) => setValue(event.target.value)}
            >
              {Object.entries(options).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          ) : (
            <input
              value={value}
              disabled={busy}
              maxLength={80}
              required
              onChange={(event) => setValue(event.target.value)}
            />
          )}
        </label>
        <button type="submit" disabled={busy || !snapshot || !value.trim()}>
          {busy ? "处理中…" : "保存偏好"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void update(getProfile)}
        >
          重新加载
        </button>
      </form>
    </section>
  );
}

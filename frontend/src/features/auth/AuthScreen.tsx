/**
 * 用途：提供互斥的登录/注册表单以及登录后的身份确认重试。
 * 边界：口令仅从当前表单读取，不进入持久化存储或 Query 缓存。
 */
import { useMutation } from "@tanstack/react-query";
import { useRef, useState, type FormEvent, type ReactElement } from "react";

import { ApiError } from "../../shared/api/http";
import {
  getCurrentIdentity,
  loginAccount,
  registerAccount,
  type Credentials,
  type CurrentIdentity,
} from "./authApi";

export type AuthScreenProps = {
  onAuthenticated(identity: CurrentIdentity): void;
};

/** 将状态码转成安全提示，不回显服务端 detail。 */
function authErrorMessage(error: unknown, mode: "login" | "register"): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "请求来源未获允许，请检查前后端地址配置。";
    if (error.status === 409 && mode === "register")
      return "用户名已存在，请更换用户名。";
    if (error.status === 422) return "提交内容不符合要求，请检查用户名和密码。";
    if (error.status === 401 && mode === "login") return "用户名或密码不正确。";
  }
  return "服务暂时不可用，请稍后重试。";
}

/** 注册后仍需登录；登录 204 后必须再以 /me 确认会话。 */
export function AuthScreen({ onAuthenticated }: AuthScreenProps): ReactElement {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirming, setConfirming] = useState(false);
  const credentialsRef = useRef<Credentials | null>(null);
  const submittingRef = useRef(false);
  const register = useMutation({
    mutationFn: () => {
      if (credentialsRef.current === null) throw new Error("缺少注册输入");
      return registerAccount(credentialsRef.current);
    },
  });
  const login = useMutation({
    mutationFn: () => {
      if (credentialsRef.current === null) throw new Error("缺少登录输入");
      return loginAccount(credentialsRef.current);
    },
  });

  async function confirmIdentity(): Promise<void> {
    setError("");
    try {
      const identity = await getCurrentIdentity();
      if (identity === null) throw new ApiError(401);
      onAuthenticated(identity);
    } catch {
      setError("登录已提交，但无法确认身份。请重新确认。");
    }
  }

  /** 表单提交只读取当前 DOM 中的口令，成功后立即清空字段。 */
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submittingRef.current || register.isPending || login.isPending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const input: Credentials = {
      username: String(data.get("username") ?? "").trim(),
      password: String(data.get("password") ?? ""),
    };
    setError("");
    setNotice("");
    if (!input.username || !input.password) {
      setError("请输入用户名和密码。");
      return;
    }
    if (mode === "register" && input.password.length < 12) {
      setError("注册密码至少需要 12 个字符。");
      return;
    }
    submittingRef.current = true;
    credentialsRef.current = input;
    if (mode === "register") {
      try {
        const identity = await register.mutateAsync();
        form.reset();
        setUsername(identity.username);
        setMode("login");
        setNotice("注册成功，请登录。");
      } catch (cause) {
        setError(authErrorMessage(cause, mode));
      } finally {
        credentialsRef.current = null;
        submittingRef.current = false;
      }
      return;
    }
    try {
      await login.mutateAsync();
    } catch (cause) {
      setError(authErrorMessage(cause, mode));
      return;
    } finally {
      credentialsRef.current = null;
      submittingRef.current = false;
    }
    form.reset();
    setUsername(input.username);
    setConfirming(true);
    await confirmIdentity();
  }

  const pending = register.isPending || login.isPending;
  return (
    <main className="auth-page">
      <section className="auth-card" aria-label="身份验证">
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            O
          </span>
          <span>ODMFlow</span>
        </div>
        <h1>欢迎使用 ODMFlow</h1>
        <p className="auth-intro">
          从身份验证开始，进入面向业务流程的 Agent 工作区。
        </p>
        {confirming ? (
          <div className="auth-confirmation">
            <h2>正在确认身份</h2>
            <p>登录请求已完成，正在向服务端确认当前账号。</p>
            {error && (
              <p role="alert" className="form-message error">
                {error}
              </p>
            )}
            <button
              type="button"
              className="primary-button"
              onClick={() => void confirmIdentity()}
            >
              重新确认
            </button>
          </div>
        ) : (
          <>
            <div className="auth-tabs" role="tablist" aria-label="身份操作">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "login"}
                onClick={() => {
                  setMode("login");
                  setError("");
                  setNotice("");
                }}
              >
                登录
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "register"}
                onClick={() => {
                  setMode("register");
                  setError("");
                  setNotice("");
                }}
              >
                注册
              </button>
            </div>
            <form
              key={mode}
              aria-label={mode === "login" ? "登录表单" : "注册表单"}
              onSubmit={(event) => void submit(event)}
            >
              <label htmlFor="username">用户名</label>
              <input
                id="username"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                maxLength={120}
              />
              <label htmlFor="password">密码</label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                required
                minLength={mode === "register" ? 12 : 1}
              />
              {mode === "register" && (
                <p className="field-hint">
                  密码至少 12 个字符；注册后需再登录。
                </p>
              )}
              {notice && (
                <p role="status" className="form-message success">
                  {notice}
                </p>
              )}
              {error && (
                <p role="alert" className="form-message error">
                  {error}
                </p>
              )}
              <button
                type="submit"
                className="primary-button"
                disabled={pending}
              >
                {pending ? "正在提交…" : mode === "login" ? "登录" : "创建账号"}
              </button>
            </form>
          </>
        )}
      </section>
    </main>
  );
}

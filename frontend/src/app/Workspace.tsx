/**
 * 用途：呈现已认证工作区，组装私人持久对话与真实退出入口。
 * 边界：对话由后端 MySQL 保存，工作区不自行持久化身份或消息。
 */
import { useMutation } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import {
  getCurrentIdentity,
  logoutAccount,
  type CurrentIdentity,
} from "../features/auth/authApi";
import { ConversationWorkspace } from "../features/conversations/ConversationWorkspace";
import { ProfilePanel } from "../features/profiles/ProfilePanel";
import { ApiError } from "../shared/api/http";

export type WorkspaceProps = {
  identity: CurrentIdentity;
  onLoggedOut(): void;
};

/** 退出成功或服务端确认会话失效才切换为游客。 */
export function Workspace({
  identity,
  onLoggedOut,
}: WorkspaceProps): ReactElement {
  const [error, setError] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const logout = useMutation({ mutationFn: logoutAccount });

  async function handleLogout(): Promise<void> {
    setError("");
    try {
      await logout.mutateAsync();
      onLoggedOut();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        try {
          if ((await getCurrentIdentity()) === null) {
            onLoggedOut();
            return;
          }
        } catch {
          // 无法确认会话失效时，仍留在工作区并提示用户重试。
        }
      }
      setError("退出未完成，请稍后重试。");
    }
  }

  return (
    <div className="app-shell">
      <main className="workspace">
        <header className="workspace-header">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              O
            </span>
            <span className="brand-name">ODMFlow</span>
          </div>
          <div className="account-actions">
            <button
              type="button"
              className="logout-button"
              onClick={() => setProfileOpen(!profileOpen)}
            >
              我的画像
            </button>
            <span className="account-name" aria-label="当前账号">
              {identity.username}
            </span>
            <button
              type="button"
              className="logout-button"
              disabled={logout.isPending}
              onClick={() => void handleLogout()}
            >
              {logout.isPending ? "正在退出…" : "退出登录"}
            </button>
          </div>
        </header>
        {error && (
          <p role="alert" className="workspace-error">
            {error}
          </p>
        )}
        {profileOpen && (
          <ProfilePanel
            onClose={() => setProfileOpen(false)}
            onUnauthorized={onLoggedOut}
          />
        )}
        <ConversationWorkspace onUnauthorized={onLoggedOut} />
      </main>
    </div>
  );
}

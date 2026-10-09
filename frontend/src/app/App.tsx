/**
 * 用途：按服务端身份查询组合游客、加载、错误与工作区四种界面。
 * 边界：用户权限由后端决定；跨账号切换时清空全部内存查询缓存。
 */
import { useQueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { AuthScreen } from "../features/auth/AuthScreen";
import { type CurrentIdentity } from "../features/auth/authApi";
import {
  identityQueryKey,
  useCurrentIdentity,
} from "../features/auth/identityQuery";
import { Workspace } from "./Workspace";

/** 首次及刷新时以 /me 为准；只有明确 401 才展示登录表单。 */
export function App(): ReactElement {
  const queryClient = useQueryClient();
  const identity = useCurrentIdentity();

  function setIdentity(next: CurrentIdentity | null): void {
    // 保留当前身份 Query 的观察者；clear() 会解除订阅，导致登录成功后页面卡在确认态。
    queryClient.getMutationCache().clear();
    queryClient.removeQueries({
      predicate: (query) =>
        query.queryKey.length !== 2 ||
        query.queryKey[0] !== identityQueryKey[0] ||
        query.queryKey[1] !== identityQueryKey[1],
    });
    queryClient.setQueryData(identityQueryKey, next);
  }

  if (identity.isPending)
    return (
      <main className="status-page">
        <p role="status">正在确认身份…</p>
      </main>
    );
  if (identity.isError) {
    return (
      <main className="status-page">
        <h1>无法确认登录状态</h1>
        <p>请检查网络或稍后重试。</p>
        <button type="button" onClick={() => void identity.refetch()}>
          重新尝试
        </button>
      </main>
    );
  }
  if (identity.data === null)
    return <AuthScreen onAuthenticated={setIdentity} />;
  return (
    <Workspace
      key={identity.data.user_id}
      identity={identity.data}
      onLoggedOut={() => setIdentity(null)}
    />
  );
}

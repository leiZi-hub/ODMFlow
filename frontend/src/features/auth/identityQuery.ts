/**
 * 用途：定义当前身份的服务端查询。
 * 边界：缓存仅存在于内存，401 与网络/服务故障由 API 层区分。
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { getCurrentIdentity, type CurrentIdentity } from "./authApi";

export const identityQueryKey = ["auth", "current"] as const;

/** 首次加载及页面刷新均向服务端确认当前会话。 */
export function useCurrentIdentity(): UseQueryResult<
  CurrentIdentity | null,
  Error
> {
  return useQuery({
    queryKey: identityQueryKey,
    queryFn: getCurrentIdentity,
    retry: false,
    staleTime: 0,
  });
}

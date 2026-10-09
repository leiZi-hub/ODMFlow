/** 用途：封装本人画像契约和统一HTTP调用；不缓存身份、画像或CSRF令牌。 */
import { ApiError, apiRequest } from "../../shared/api/http";
import { getCsrfToken } from "../auth/authApi";

export const profileFields = {
  language: { label: "回答语言", values: { "zh-CN": "中文", en: "英文" } },
  response_detail: {
    label: "回答详略",
    values: { brief: "简洁", balanced: "适中", detailed: "详细" },
  },
  explanation_style: {
    label: "解释方式",
    values: { general: "通用解释", java_comparison: "对照 Java 解释" },
  },
  business_role: { label: "业务角色", values: null },
  product_focus: { label: "产品方向", values: null },
} as const;
export type ProfileField = keyof typeof profileFields;
export type ProfileItem = {
  field_key: ProfileField;
  value: string | null;
  origin: "manual" | "conversation" | "deleted";
  suppressed: boolean;
  source_conversation_id: string | null;
  source_message_id: number | null;
  evidence: string | null;
  updated_at: string;
};
export type ProfileSnapshot = { revision: number; items: ProfileItem[] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 校验网络结构；未知字段/版本或不一致删除状态不能作为可编辑快照。 */
async function readSnapshot(response: Response): Promise<ProfileSnapshot> {
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(null);
  }
  if (
    !isRecord(data) ||
    !Number.isSafeInteger(data.revision) ||
    Number(data.revision) < 0 ||
    !Array.isArray(data.items) ||
    data.items.length > 5
  )
    throw new ApiError(null);
  const items = data.items.map((item: unknown): ProfileItem => {
    if (
      !isRecord(item) ||
      typeof item.field_key !== "string" ||
      !Object.hasOwn(profileFields, item.field_key) ||
      !["manual", "conversation", "deleted"].includes(String(item.origin)) ||
      typeof item.suppressed !== "boolean" ||
      !(item.value === null || typeof item.value === "string") ||
      !(
        item.source_conversation_id === null ||
        typeof item.source_conversation_id === "string"
      ) ||
      !(
        item.source_message_id === null ||
        (Number.isSafeInteger(item.source_message_id) &&
          Number(item.source_message_id) > 0)
      ) ||
      !(item.evidence === null || typeof item.evidence === "string") ||
      typeof item.updated_at !== "string" ||
      !Number.isFinite(Date.parse(item.updated_at)) ||
      item.suppressed !== (item.origin === "deleted") ||
      item.suppressed !== (item.value === null)
    )
      throw new ApiError(null);
    return item as ProfileItem;
  });
  if (new Set(items.map((item) => item.field_key)).size !== items.length)
    throw new ApiError(null);
  return { revision: Number(data.revision), items };
}

/** 登录Cookie决定归属，不向接口提交user_id。 */
export async function getProfile(): Promise<ProfileSnapshot> {
  return readSnapshot(await apiRequest("/memory/profile"));
}

/** 版本冲突传播给面板，不重试或无声覆盖。 */
export async function editProfile(
  revision: number,
  field_key: ProfileField,
  value: string,
): Promise<ProfileSnapshot> {
  const token = await getCsrfToken();
  return readSnapshot(
    await apiRequest("/memory/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ revision, field_key, value }),
    }),
  );
}

/** 删除携带版本；后端保留抑制标记，人工重新设置才恢复。 */
export async function deleteProfile(
  revision: number,
  field: ProfileField,
): Promise<ProfileSnapshot> {
  const token = await getCsrfToken();
  return readSnapshot(
    await apiRequest(`/memory/profile/${field}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ revision }),
    }),
  );
}

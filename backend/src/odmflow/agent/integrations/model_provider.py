"""从明确配置创建 OpenAI 兼容的 LangChain 聊天模型。

边界：不探测服务商、不发送请求；真实兼容性须用户配好 Key 后单独验证。
"""

import os
from urllib.parse import urlsplit

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ..configuration import AgentTimeoutSettings


def build_chat_model(settings: AgentTimeoutSettings) -> ChatOpenAI | None:
    """读取模型名、Key 与 Base URL，缺项时保持 Agent 禁用。

    Args:
        settings: 组合层从应用快照转换的等待策略，不读取旧环境策略。
    Returns:
        配置齐全时的聊天模型，否则为 None。

    Raises:
        ValueError: 非本地明文 HTTP、带账号信息或无效的模型 URL。
    """

    model_name = os.environ.get("ODMFLOW_LLM_MODEL", "").strip()
    api_key = os.environ.get("ODMFLOW_LLM_API_KEY", "").strip()
    base_url = os.environ.get("ODMFLOW_LLM_BASE_URL", "").strip()
    if not all((model_name, api_key, base_url)) or any(
        "请输入" in value for value in (model_name, api_key, base_url)
    ):
        return None
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ODMFLOW_LLM_BASE_URL must be a valid HTTPS endpoint")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote model endpoint must use HTTPS")
    model = ChatOpenAI(
        model=model_name,
        api_key=SecretStr(api_key),
        base_url=base_url,
        timeout=settings.llm_request_seconds,
        max_retries=0,
        max_completion_tokens=800,
    )
    return model

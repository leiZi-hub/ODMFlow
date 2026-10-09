"""用途：有限大小读取应用TOML并定位明确文件；边界：不读.env、不创建文件或目录。"""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from .legacy import reject_legacy_policy_variables
from .models import ApplicationSettings, ConfigurationError, parse_application_settings


def load_application_settings(
    *, environment: Mapping[str, str] | None = None, project_root: Path | None = None
) -> ApplicationSettings:
    """加载实际策略文件，不自动把模板当成配置。

    Args:
        environment: 注入环境映射；默认进程环境，仅选择器/旧键检查。
        project_root: 显式项目根，供隔离测试；缺省从源码位置核验。
    Returns:
        经严格校验的不可变快照。
    Raises:
        ConfigurationError: 旧策略、路径/文件/语法/类型/预算非法。
    """
    env = os.environ if environment is None else environment
    reject_legacy_policy_variables(env)
    selected = env.get("ODMFLOW_CONFIG_FILE", "application.toml").strip()
    if not selected:
        raise ConfigurationError("ODMFLOW_CONFIG_FILE 不可为空")
    path = Path(selected)
    if not path.is_absolute():
        root = project_root if project_root is not None else _source_root()
        if root is None:
            raise ConfigurationError("非源码部署请将 ODMFLOW_CONFIG_FILE 指定为绝对路径")
        path = root / path
    if path.name.endswith(".example"):
        raise ConfigurationError("不能使用 .example 运行；请复制模板为实际 application.toml")
    try:
        if not path.is_file():
            raise ConfigurationError(
                "缺少应用配置：请在后端根目录复制 application.toml.example 为实际文件，"
                "并设置 ODMFLOW_CONFIG_FILE"
            )
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ConfigurationError("应用配置超过64 KiB，请缩小文件")
        document = tomllib.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError) as error:
        if isinstance(error, ConfigurationError):
            raise
        raise ConfigurationError("应用配置无法读取或不是有效UTF-8/TOML，请检查实际文件") from None
    return parse_application_settings(document)


def _source_root() -> Path | None:
    """只核验本模块对应源码根，不向当前目录或磁盘扫描。"""
    root = Path(__file__).resolve().parents[3]
    if (root / "pyproject.toml").is_file() and (root / "src/odmflow/configuration").is_dir():
        return root
    return None


def resolve_project_resource_path(value: str) -> Path:
    """定位应用资源文件，不随IDE工作目录改变，也不创建目录。

    Args:
        value: 已验证的绝对路径，或源码项目根相对路径。
    Returns:
        规范化资源路径；允许首次运行时文件尚不存在。
    Raises:
        ConfigurationError: 非源码部署却配置了相对路径。
    """
    path = Path(value)
    if not path.is_absolute():
        root = _source_root()
        if root is None:
            raise ConfigurationError("非源码部署请将应用资源文件配置为绝对路径")
        path = root / path
    return path.resolve()

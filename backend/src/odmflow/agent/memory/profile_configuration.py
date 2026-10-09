"""用户画像准备配置；只管理提取开关与等待预算，不读取密钥或判断业务。"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileSettings:
    """关闭时不自动提取或注入画像，人工管理接口仍可使用。"""

    enabled: bool = True
    timeout_seconds: float = 10

    def __post_init__(self) -> None:
        """拒绝非有限、非正和超过一分钟的提取等待。"""
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 60:
            raise ValueError("画像提取等待必须在0到60秒之间")

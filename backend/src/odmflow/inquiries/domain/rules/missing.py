"""询盘缺失信息规则。

用途：
    按业务职责定义基础字段、产品硬件、连接能力和合规信息的缺失检查。

边界：
    每个函数只返回自己负责的缺失项，不决定最终评估状态，也不修改输入需求。
"""

from ..contracts import (
    AndroidDistribution,
    ConnectivityType,
    MarketRegion,
    MissingField,
    PeripheralType,
    ProductType,
    RequirementDraft,
)


def _append_missing(
    results: list[MissingField],
    condition: bool,
    field_path: str,
    reason: str,
) -> None:
    """在条件成立时向当前规则结果追加一个缺失项。"""

    if condition:
        results.append(MissingField(field_path=field_path, reason=reason))


def check_base_fields(requirement: RequirementDraft) -> tuple[MissingField, ...]:
    """检查每类 Android ODM 询盘都需要确认的基础字段。"""

    missing: list[MissingField] = []
    project = requirement.project
    hardware = requirement.hardware
    software = requirement.software

    _append_missing(
        missing,
        project.product_type is None,
        "project.product_type",
        "产品类型尚未确认",
    )
    _append_missing(missing, project.use_case is None, "project.use_case", "使用场景尚未确认")
    _append_missing(missing, project.quantity is None, "project.quantity", "采购数量尚未确认")
    _append_missing(
        missing,
        not project.target_markets,
        "project.target_markets",
        "目标市场尚未确认",
    )
    _append_missing(
        missing,
        project.mass_production_deadline is None,
        "project.mass_production_deadline",
        "量产目标时间尚未确认",
    )
    _append_missing(
        missing,
        software.android_version is None,
        "software.android_version",
        "Android 版本尚未确认",
    )
    _append_missing(
        missing,
        software.android_distribution in {None, AndroidDistribution.UNSPECIFIED},
        "software.android_distribution",
        "Android 发行方式尚未确认",
    )
    _append_missing(
        missing,
        software.google_mobile_services_required is None,
        "software.google_mobile_services_required",
        "是否需要 Google Mobile Services 尚未确认",
    )
    _append_missing(missing, not hardware.connectivity, "hardware.connectivity", "连接方式尚未确认")

    return tuple(missing)


def check_product_hardware_fields(requirement: RequirementDraft) -> tuple[MissingField, ...]:
    """检查由产品类型触发的显示、电池和防护字段。"""

    missing: list[MissingField] = []
    product_type = requirement.project.product_type
    hardware = requirement.hardware

    if product_type in {ProductType.TABLET, ProductType.SMART_DISPLAY}:
        _append_missing(
            missing,
            hardware.display_size_inches is None,
            "hardware.display_size_inches",
            "当前产品类型需要确认屏幕尺寸",
        )
        _append_missing(
            missing,
            hardware.resolution is None,
            "hardware.resolution",
            "当前产品类型需要确认分辨率",
        )

    if product_type in {ProductType.TABLET, ProductType.HANDHELD}:
        _append_missing(
            missing,
            hardware.battery_mah is None,
            "hardware.battery_mah",
            "移动设备需要确认电池容量",
        )

    if product_type is ProductType.HANDHELD:
        _append_missing(
            missing,
            hardware.rugged_ip_rating is None,
            "hardware.rugged_ip_rating",
            "手持终端需要确认防护等级",
        )

    return tuple(missing)


def check_connectivity_fields(requirement: RequirementDraft) -> tuple[MissingField, ...]:
    """检查蜂窝连接和 NFC 外设需要补充的使用信息。"""

    missing: list[MissingField] = []
    hardware = requirement.hardware
    has_cellular = bool(
        hardware.connectivity & {ConnectivityType.CELLULAR_4G, ConnectivityType.CELLULAR_5G}
    )

    _append_missing(
        missing,
        has_cellular and hardware.cellular_requirement_notes is None,
        "hardware.cellular_requirement_notes",
        "蜂窝连接需要确认频段、SIM 或运营商要求",
    )
    _append_missing(
        missing,
        PeripheralType.NFC in hardware.peripherals and hardware.nfc_usage is None,
        "hardware.nfc_usage",
        "NFC 外设需要确认使用场景",
    )

    return tuple(missing)


def check_compliance_fields(requirement: RequirementDraft) -> tuple[MissingField, ...]:
    """检查目标市场触发的合规信息。"""

    if (
        MarketRegion.EU in requirement.project.target_markets
        and not requirement.compliance.certifications
    ):
        return (
            MissingField(
                field_path="compliance.certifications",
                reason="欧盟项目需要明确记录客户提出或售前待确认的认证需求",
            ),
        )

    return ()

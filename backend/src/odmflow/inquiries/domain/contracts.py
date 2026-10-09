"""询盘领域数据契约。

用途：
    定义 Android ODM 询盘的输入、需求分区与评估结果结构，并执行基础格式校验。

边界：
    不判断字段是否缺失、需求是否冲突或产品是否可生产，也不访问外部服务。
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ResolutionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{3,5}x\d{3,5}$"),
]
PositiveInt = Annotated[int, Field(gt=0)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]


class DomainModel(BaseModel):
    """提供禁止额外字段且不可变的领域模型基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ProductType(StrEnum):
    """表示当前项目支持识别的 Android ODM 产品类型。"""

    TABLET = "tablet"
    HANDHELD = "handheld"
    SMART_DISPLAY = "smart_display"
    SELF_SERVICE_TERMINAL = "self_service_terminal"
    OTHER = "other"


class MarketRegion(StrEnum):
    """表示产品计划销售或交付的目标市场区域。"""

    CHINA = "china"
    EU = "eu"
    NORTH_AMERICA = "north_america"
    SOUTHEAST_ASIA = "southeast_asia"
    MIDDLE_EAST = "middle_east"
    OTHER = "other"


class ConnectivityType(StrEnum):
    """表示终端需要支持的网络或无线连接能力。"""

    WIFI = "wifi"
    BLUETOOTH = "bluetooth"
    ETHERNET = "ethernet"
    CELLULAR_4G = "4g"
    CELLULAR_5G = "5g"
    GNSS = "gnss"


class PeripheralType(StrEnum):
    """表示终端需要集成的外设能力。"""

    NFC = "nfc"
    BARCODE_SCANNER = "barcode_scanner"
    CAMERA = "camera"
    FINGERPRINT = "fingerprint"
    PRINTER = "printer"
    SERIAL_PORT = "serial_port"
    USB = "usb"


class AndroidDistribution(StrEnum):
    """表示设备采用的 Android 软件发行形态。"""

    GMS = "gms"
    AOSP = "aosp"
    CUSTOM = "custom"
    UNSPECIFIED = "unspecified"


class AssessmentStatus(StrEnum):
    """表示需求完成规则评估后的下一步状态。"""

    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_CLARIFICATION = "needs_clarification"
    HAS_CONFLICTS = "has_conflicts"


class ProjectSpec(DomainModel):
    """表示订单规模、用途、市场和交付时间等项目级需求。"""

    product_type: ProductType | None = None
    use_case: NonBlankText | None = None
    quantity: PositiveInt | None = None
    target_markets: frozenset[MarketRegion] = Field(default_factory=frozenset)
    sample_deadline: date | None = None
    mass_production_deadline: date | None = None


class HardwareSpec(DomainModel):
    """表示显示、存储、电池、连接和外设等硬件需求。"""

    display_size_inches: PositiveDecimal | None = None
    resolution: ResolutionText | None = None
    ram_gb: PositiveInt | None = None
    storage_gb: PositiveInt | None = None
    battery_mah: PositiveInt | None = None
    connectivity: frozenset[ConnectivityType] = Field(default_factory=frozenset)
    peripherals: frozenset[PeripheralType] = Field(default_factory=frozenset)
    rugged_ip_rating: NonBlankText | None = None
    cellular_requirement_notes: NonBlankText | None = None
    nfc_usage: NonBlankText | None = None


class SoftwareSpec(DomainModel):
    """表示 Android 版本、发行形态和系统定制等软件需求。"""

    android_version: NonBlankText | None = None
    android_distribution: AndroidDistribution | None = None
    google_mobile_services_required: bool | None = None
    kiosk_mode_required: bool | None = None
    ota_required: bool | None = None
    preinstalled_apps: tuple[NonBlankText, ...] = ()
    software_notes: NonBlankText | None = None


class CustomizationSpec(DomainModel):
    """表示外观、包装与软硬件定制意向。"""

    logo_customization: bool | None = None
    enclosure_customization: bool | None = None
    packaging_customization: bool | None = None
    hardware_customization: bool | None = None
    hardware_customization_notes: tuple[NonBlankText, ...] = ()
    customization_notes: tuple[NonBlankText, ...] = ()


class ComplianceSpec(DomainModel):
    """表示目标市场提出的认证和合规信息。"""

    certifications: frozenset[NonBlankText] = Field(default_factory=frozenset)
    certification_notes: NonBlankText | None = None


class RequirementDraft(DomainModel):
    """聚合尚未完成人工确认的各类结构化需求。"""

    project: ProjectSpec = Field(default_factory=ProjectSpec)
    hardware: HardwareSpec = Field(default_factory=HardwareSpec)
    software: SoftwareSpec = Field(default_factory=SoftwareSpec)
    customization: CustomizationSpec = Field(default_factory=CustomizationSpec)
    compliance: ComplianceSpec = Field(default_factory=ComplianceSpec)


class MissingField(DomainModel):
    """表示业务评估发现的一项待补充信息。"""

    field_path: NonBlankText
    reason: NonBlankText


class RequirementConflict(DomainModel):
    """表示多个需求字段之间的一项确定性冲突。"""

    code: NonBlankText
    field_paths: tuple[NonBlankText, ...]
    reason: NonBlankText


class RequirementAssessment(DomainModel):
    """表示需求规则评估产生的状态、缺失项和冲突集合。"""

    status: AssessmentStatus
    missing_fields: tuple[MissingField, ...]
    conflicts: tuple[RequirementConflict, ...]
    requirement: RequirementDraft

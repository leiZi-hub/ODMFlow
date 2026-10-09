"""显式 Agent 工具清单。

用途：集中选择当前允许交给模型的工具并固定顺序。
边界：不扫描模块、不定义 ODM 规则、不执行工具业务。
"""

from collections.abc import Mapping
from types import MappingProxyType

from odmflow.business_actions.domain import AfterSalesApplication, OrderApplication

from ..tasks.contracts import Capability
from .after_sales_lookup import (
    GetMyAfterSalesInput,
    ListMyAfterSalesInput,
    execute_after_sales_read,
)
from .business_applications import execute_application
from .contracts import CapabilityDefinition, CapabilityRisk
from .knowledge_search import KnowledgeSearchInput, execute_knowledge
from .odm_assessment import OdmAssessmentInput, execute_assessment
from .order_lookup import GetMyOrderInput, ListMyOrdersInput, execute_order_read


def build_capability_catalog() -> Mapping[Capability, CapabilityDefinition]:
    """返回固定能力目录；构造时无数据库/模型IO。

    Returns:
        不可由模型修改的八项能力定义；模型只能准备确认卡，没有确认执行或跨用户工具。"""
    return MappingProxyType(
        {
            Capability.PREPARE_ORDER_APPLICATION: CapabilityDefinition(
                Capability.PREPARE_ORDER_APPLICATION,
                OrderApplication,
                CapabilityRisk.CONFIRMATION_REQUIRED,
                "仅用户要求申请且型号/数量/地区/配置明确时准备模拟订单确认卡；不猜字段，不执行下单，等待用户点击确认",
                execute_application,
            ),
            Capability.PREPARE_AFTER_SALES_APPLICATION: CapabilityDefinition(
                Capability.PREPARE_AFTER_SALES_APPLICATION,
                AfterSalesApplication,
                CapabilityRisk.CONFIRMATION_REQUIRED,
                "为本人已交付明确订单准备模拟售后确认卡；需故障、时间、复现和处理意向。受理不代表批准退换，必须用户点击确认",
                execute_application,
            ),
            Capability.LIST_MY_AFTER_SALES: CapabilityDefinition(
                Capability.LIST_MY_AFTER_SALES,
                ListMyAfterSalesInput,
                CapabilityRisk.PRIVATE_AFTER_SALES_READ,
                "查询本人最近十条模拟售后受理记录；不审批或更改状态",
                execute_after_sales_read,
            ),
            Capability.GET_MY_AFTER_SALES: CapabilityDefinition(
                Capability.GET_MY_AFTER_SALES,
                GetMyAfterSalesInput,
                CapabilityRisk.PRIVATE_AFTER_SALES_READ,
                "查询本人明确受理编号的模拟售后记录；不得猜编号",
                execute_after_sales_read,
            ),
            Capability.LIST_MY_ORDERS: CapabilityDefinition(
                Capability.LIST_MY_ORDERS,
                ListMyOrdersInput,
                CapabilityRisk.PRIVATE_READONLY,
                "查询本人最近最多十筆模拟订单，has_more表示仍有更多；无目标先列表",
                execute_order_read,
            ),
            Capability.GET_MY_ORDER: CapabilityDefinition(
                Capability.GET_MY_ORDER,
                GetMyOrderInput,
                CapabilityRisk.PRIVATE_READONLY,
                "查询本人明确订单号的模拟详情与进度；号码须来自本人原话或本人列表",
                execute_order_read,
            ),
            Capability.ASSESS_ODM_REQUIREMENTS: CapabilityDefinition(
                Capability.ASSESS_ODM_REQUIREMENTS,
                OdmAssessmentInput,
                CapabilityRisk.READONLY_COMPUTATION,
                "评估Android ODM需求缺失及冲突",
                execute_assessment,
            ),
            Capability.RAG_SEARCH: CapabilityDefinition(
                Capability.RAG_SEARCH,
                KnowledgeSearchInput,
                CapabilityRisk.PUBLIC_KNOWLEDGE,
                "查询产品、定制和售后政策；纯问候不用检索",
                execute_knowledge,
            ),
        }
    )

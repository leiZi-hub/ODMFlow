"""用途：确定性确认图；边界：只持久化动作引用，不序列化身份、连接或参数。"""

import asyncio
from dataclasses import dataclass
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from odmflow.business_actions.application import BusinessActionService
from odmflow.business_actions.domain import ActionConflict


class ApprovalState(TypedDict, total=False):
    """图游标只保存动作ID、版本和有限状态；不复制业务快照。"""

    action_id: str
    revision: int
    confirmed: bool
    status: str


@dataclass(frozen=True)
class TrustedApprovalContext:
    """每次调用重新绑定的可信身份和端口；不会进入checkpoint。"""

    owner_id: str
    business: BusinessActionService


async def prepare(state: ApprovalState, runtime: Runtime[TrustedApprovalContext]) -> ApprovalState:
    """确认服务端引用仍属于本人；该节点重放没有写业务副作用。"""
    view = await asyncio.to_thread(
        runtime.context.business.get, runtime.context.owner_id, state["action_id"]
    )
    if view.revision != state["revision"]:
        raise ActionConflict("revision_changed")
    return {"status": view.status}


def await_confirmation(state: ApprovalState) -> ApprovalState:
    """原生中断释放本轮连接；恢复时从节点开头重跑，因此节点不能先写业务。"""
    decision = interrupt({"action_id": state["action_id"], "revision": state["revision"]})
    if type(decision) is not bool:
        raise ActionConflict("invalid_internal_decision")
    return {"confirmed": decision}


async def execute_confirmed_action(
    state: ApprovalState, runtime: Runtime[TrustedApprovalContext]
) -> ApprovalState:
    """恢复只调用事务门禁；参数由权威库读取，原生节点重放依然幂等。"""
    view = await asyncio.to_thread(
        runtime.context.business.decide,
        runtime.context.owner_id,
        state["action_id"],
        state["revision"],
        state["confirmed"],
    )
    return {"status": view.status}


def finalize(state: ApprovalState) -> ApprovalState:
    """结束有限写图，不调用模型，不重置原任务图的预算。"""
    return {"status": state["status"]}


def build_approval_graph(
    saver: AsyncSqliteSaver,
) -> CompiledStateGraph[ApprovalState, TrustedApprovalContext]:
    """编译四节点固定流程；SQLite仅用于本机写图游标，不代替MySQL事务。"""
    graph = StateGraph(ApprovalState, context_schema=TrustedApprovalContext)
    graph.add_node("prepare", prepare)
    graph.add_node("await_confirmation", await_confirmation)
    graph.add_node("execute_confirmed_action", execute_confirmed_action)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "await_confirmation")
    graph.add_edge("await_confirmation", "execute_confirmed_action")
    graph.add_edge("execute_confirmed_action", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=saver)

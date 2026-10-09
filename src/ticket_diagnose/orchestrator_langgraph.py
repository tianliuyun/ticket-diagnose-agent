"""LangGraph 版主 Agent 编排器 —— 用 StateGraph 重写「初筛 → 并行诊断 → 分派」流程。

与 orchestrator.py（自研 ReActLoop）接口对齐：
- 同样的工具语义（classify_ticket / dispatch_diagnosis / assign_engineer）
- 同样的 Worker 并行派发（复用 dispatch_diagnosis 的 ThreadPoolExecutor 机制）
- 返回结构兼容：{final_answer, classify_result, dispatches, workers, parallel_stats}

差异（结构化状态管理的工程化）：
- 自研版：LLM 在 ReAct 循环里自主选工具，状态是 Python dict
- LangGraph 版：流程显式建模为 StateGraph 节点图（screener→classify→dispatch→assign），
  状态 schema 化（TypedDict），节点确定性更强、可观测性更好
- 支持 graph 可视化导出（graph.draw_mermaid_png），可展示编排拓扑
"""
from typing import Dict, List, Optional, TypedDict

import time
import uuid

from .knowledge_base import KB_ENTRIES
from .workers import run_diagnosis_worker, extract_diagnosis_angles

# LangGraph 状态 Schema（结构化状态管理）
class DiagnoseState(TypedDict, total=False):
    ticket_text: str          # 工单全文
    classify_result: dict     # 初筛结果 {类别,子类,优先级,置信度}
    angles: List[str]         # 待诊断角度
    worker_results: dict      # Worker 诊断结果 {wid: {...}}
    parallel_stats: list      # 并行统计
    dispatch_summary: str     # 并行诊断汇总文本
    assign_result: str        # 派送结果文本
    final_answer: str         # 最终答案


def build_langgraph_orchestrator(dispatch_diagnosis, classify_tool, assign_tool,
                                 dispatch_engine=None, serial: bool = False,
                                 max_workers: int = 4):
    """构建 LangGraph StateGraph 编排器。

    Args:
        dispatch_diagnosis: 并行派发函数（复用 orchestrator.dispatch_diagnosis）
        classify_tool: 初筛工具函数（输入工单文本 → 分类字符串）
        assign_tool: 派送工具函数（输入 JSON → 派送结果字符串）
        serial: True 时 Worker 串行（A/B 对比用）
    """
    from langgraph.graph import StateGraph, END

    def node_screener(state: DiagnoseState) -> dict:
        """节点1：读工单 → 初筛分类。"""
        text = state["ticket_text"]
        classify_str = classify_tool(text)
        # classify_tool 返回 "类别=...,子类=...,优先级=...,置信度=..."
        parsed = {}
        for part in classify_str.replace("，", ",").split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                parsed[k.strip()] = v.strip()
        state["classify_result"] = parsed
        return {"classify_result": parsed}

    def node_route(state: DiagnoseState) -> dict:
        """节点2：根据初筛子类拆解诊断角度。"""
        cr = state.get("classify_result", {})
        sub = cr.get("子类", cr.get("sub_category", ""))
        angles = extract_diagnosis_angles(sub) or ["故障排查"]
        state["angles"] = angles[:max_workers]
        return {"angles": state["angles"]}

    def node_dispatch(state: DiagnoseState) -> dict:
        """节点3：并行派发多个诊断 Worker。"""
        angles = state.get("angles", [])
        if not angles:
            return {"dispatch_summary": "未解析出待诊断角度", "worker_results": {}, "parallel_stats": []}
        state.setdefault("worker_results", {})
        state.setdefault("parallel_stats", [])
        action_input = " | ".join(angles)

        def on_worker_done(wid, duration, angle):
            pass  # 结果已在 shared_state 记录

        summary = dispatch_diagnosis(
            action_input,
            shared_state=state,           # LangGraph state 即 shared_state
            on_worker_done=on_worker_done,
            serial=serial,
            ticket_text=state["ticket_text"],
        )
        state["dispatch_summary"] = summary
        return {"dispatch_summary": summary, "worker_results": state.get("workers", {}),
                "parallel_stats": state.get("parallel_stats", [])}

    def node_assign(state: DiagnoseState) -> dict:
        """节点4：派送对口工程师 / 低置信转专家。"""
        cr = state.get("classify_result", {})
        import json
        payload = json.dumps({
            "类别": cr.get("类别", cr.get("category", "")),
            "优先级": cr.get("优先级", cr.get("priority", "medium")),
            "置信度": float(cr.get("置信度", cr.get("confidence", 1.0)) or 1.0),
        }, ensure_ascii=False)
        state["assign_result"] = assign_tool(payload)
        return {"assign_result": state["assign_result"]}

    def node_final(state: DiagnoseState) -> dict:
        """节点5：汇总最终答案（含派送结果）。"""
        state["final_answer"] = (
            f"诊断结论：{state.get('dispatch_summary', '')}\n"
            f"派送结果：{state.get('assign_result', '')}"
        )
        return {"final_answer": state["final_answer"]}

    # 建图
    g = StateGraph(DiagnoseState)
    g.add_node("screener", node_screener)
    g.add_node("route", node_route)
    g.add_node("dispatch", node_dispatch)
    g.add_node("assign", node_assign)
    g.add_node("final", node_final)

    g.set_entry_point("screener")
    g.add_edge("screener", "route")
    g.add_edge("route", "dispatch")
    g.add_edge("dispatch", "assign")
    g.add_edge("assign", "final")
    g.add_edge("final", END)

    return g.compile()


def run_langgraph_diagnose(ticket: Dict, screener=None, dispatch_engine=None,
                           serial: bool = False, on_step: Optional[callable] = None) -> Dict:
    """LangGraph 版完整工单诊断与分派（与 orchestrator.run_diagnose 接口对齐）。

    返回结构：
      {final_answer, classify_result, dispatches, workers, parallel_stats, graph_name}
    """
    from . import orchestrator as _orch

    text = (ticket.get("title", "") + "。" + ticket.get("description", ""))

    # 复用自研版的工具包装（保证两个版本工具语义一致）
    from . import mock_backend as _mb
    _mb.install_mock_backend()
    scr = screener or _orch.InitialScreener()

    def classify_tool(action_input, **_):
        return scr.classify_ticket_str(action_input)

    eng = dispatch_engine

    def assign_tool(action_input, **_):
        nonlocal eng
        if eng is None:
            from .dispatch_builder import build_default_engine
            eng = build_default_engine()
        import json
        try:
            data = json.loads(action_input)
        except Exception as e:  # noqa: BLE001
            return f"派送参数解析失败：{type(e).__name__}: {str(e)[:120]}"
        cr = {
            "category": data.get("类别", data.get("category", "")),
            "priority": data.get("优先级", data.get("priority", "medium")),
            "confidence": data.get("置信度", data.get("confidence", 1.0)),
        }
        result = eng.assign(cr)
        eng_name = result["engineer"].name if result["engineer"] else "无"
        return (f"派送结果：工程师={eng_name}，需人工复核={result['need_review']}，"
                f"原因={result['reason']}")

    graph = build_langgraph_orchestrator(
        dispatch_diagnosis=_orch.dispatch_diagnosis,
        classify_tool=classify_tool,
        assign_tool=assign_tool,
        dispatch_engine=eng,
        serial=serial,
    )

    t0 = time.time()
    state = graph.invoke({"ticket_text": text})
    wall = round(time.time() - t0, 2)

    if on_step:
        on_step({"graph": "langgraph", "wall_clock": wall, "state_keys": list(state.keys())})

    # 记录初筛结果（与自研版对齐）
    pre = scr.classify(text)
    return {
        "final_answer": state.get("final_answer", ""),
        "classify_result": {
            "类别": pre.category, "子类": pre.sub_category,
            "优先级": pre.priority, "置信度": pre.confidence},
        "main_trace": [{"graph": "langgraph", "wall_clock": wall}],
        "workers": state.get("worker_results", {}),
        "dispatches": [{"angles": state.get("angles", []),
                        "worker_ids": list(state.get("worker_results", {}).keys())}],
        "parallel_stats": state.get("parallel_stats", []),
        "graph_name": "langgraph",
    }

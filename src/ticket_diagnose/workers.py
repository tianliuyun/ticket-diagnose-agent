"""诊断 Worker：复用 parallel-code-reviewer 的「独立 ReAct 子 Agent + 并行派发」机制，
把「读文件审查」改成「对工单某一角度做专项诊断」。

每个诊断 Worker 是一个独立的 ReActLoop，只带一个工具 look_up_kb（查故障知识库），
针对分配到的诊断角度（如「登录连接」「性能卡顿」）产出结构化诊断结论。
多个 Worker 由主 Agent 通过 dispatch_diagnosis 并行派发（ThreadPoolExecutor）。

本文件把原 parallel-code-reviewer 的 SUBAGENT_SYSTEM 与单个 Worker 执行逻辑，
改造为「工单专项诊断」语义，离线（Mock 后端）可跑通。
"""
import re
from typing import Callable, Dict, List, Optional

from code_reviewer.react_loop import ReActLoop
from code_reviewer.react_loop import build_tools_desc

from .knowledge_base import search_kb, search_kb_fuzzy

# 诊断 Worker 的系统提示（角色 = 工单专项诊断员），可被 {tools_desc} 替换工具说明
WORKER_SYSTEM = """你是企业 IT 故障工单的专项诊断员。你只有 1 个工具：
- look_up_kb：查故障知识库中对某概念的排障条目（参数=故障概念名）

请对分配给你负责的诊断角度做深度排查：
1. 先 look_up_kb 查该角度的知识库条目（根因 / 处置 / 危险动作）
2. 结合工单症状给出针对性的诊断结论（可疑根因、建议处置、风险提醒）
3. 用 Final Answer 输出结构化诊断（根因 / 处置 / 风险各一行）

【输出格式——必须严格遵守，不要使用 XML/function-calling 格式】
每轮严格按以下三行输出（先 Thought 再 Action）：
Thought: 你的推理，分析还需做什么
Action: look_up_kb
Action Input: 故障概念名

工具执行后会得到 Observation，然后输出：
Thought: 我已获得知识库信息，完成诊断
Final Answer: 根因：xxx；处置：xxx；风险：xxx

【示例】
Thought: 需要先查知识库该角度的排障条目
Action: look_up_kb
Action Input: 登录连接
Observation: 【登录连接】大类=云桌面 征兆=... 根因=... 处置=... 危险动作=...
Thought: 已获得知识库信息，完成诊断
Final Answer: 根因：认证服务负载高；处置：按知识库标准流程；风险：注意危险动作提醒

规则：
- 每轮只调一次工具，等 Observation 再决定下一步
- Action 必须是 look_up_kb，Action Input 是该工具的参数字符串
- 禁止输出 XML 标签或函数调用格式"""


def _look_up_kb_tool(concept: str, **_) -> str:
    """知识库查询工具：先精确匹配概念，再模糊匹配（子串/征兆），未命中返回提示。

    真实 LLM 主 Agent 拆出的诊断角度是自由文本（如「存储降级」「超融合集群」），
    未必与知识库概念名（如「节点故障」「存储集群」）完全一致——模糊兜底保证
    Worker 总能拿到相关排障条目，而不是空手而归。
    """
    entry = search_kb(concept)
    if entry:
        return (f"【{concept}】大类={entry.get('大类')} 征兆={entry.get('征兆')} "
                f"根因={entry.get('根因')} 处置={entry.get('处置')} "
                f"危险动作={entry.get('危险动作')}")
    hits = search_kb_fuzzy(concept)
    if hits:
        parts = []
        for h in hits[:2]:
            parts.append(f"【{h.get('概念')}】大类={h.get('大类')} 征兆={h.get('征兆')} "
                         f"根因={h.get('根因')} 处置={h.get('处置')} "
                         f"危险动作={h.get('危险动作')}")
        return "；".join(parts)
    return f"知识库未命中概念：{concept}（可能需人工建条目）"


def extract_diagnosis_angles(ticket_text: str, category: str = "") -> List[str]:
    """从工单文本中提取「需要并行诊断的角度」（故障概念名）。

    规则（确定性、可单测）：
    1. 扫描知识库概念，凡概念名出现在工单文本里即视为一个诊断角度（去重）；
    2. 补兜底：工单里含某产品大类关键词（如"存储"/"云桌面"）但没命中具体概念时，
       加上该大类的第一个概念，保证每个相关模块都有 Worker 排查。
    3. 一个都没命中则回退为默认角度。
    """
    from .knowledge_base import KB_ENTRIES
    angles = [c for c in KB_ENTRIES.keys() if c in ticket_text]
    # 大类兜底：按大类关键词补一个该模块的概念
    module_concepts = {}
    for concept, entry in KB_ENTRIES.items():
        module_concepts.setdefault(entry.get("大类"), concept)
    for module_name, first_concept in module_concepts.items():
        if module_name in ticket_text and first_concept not in angles:
            angles.append(first_concept)
    # 显式 category 兜底
    if category and category in module_concepts and module_concepts[category] not in angles:
        angles.append(module_concepts[category])
    # 去重保序
    seen, out = set(), []
    for a in angles:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out or ["其他问题"]


def run_diagnosis_worker(worker_name: str, ticket_text: str, angle: str,
                         on_step: Optional[Callable] = None) -> Dict:
    """跑一个诊断 Worker（独立 ReActLoop = 知识库查询），返回结构化结果。"""
    q = (f"工单症状：{ticket_text}\n"
         f"请对诊断角度「{angle}」做专项诊断。")
    loop = ReActLoop(
        agent_name=worker_name,
        tools={"look_up_kb": (_look_up_kb_tool, "查询故障知识库，参数=故障概念名")},
        max_steps=3,
        system_prompt=WORKER_SYSTEM,
    )
    res = loop.run(q, on_step=on_step)
    return {
        "agent": worker_name,
        "angle": angle,
        "final_answer": res["final_answer"],
        "trace": res["trace"],
        "duration": res["duration"],
    }
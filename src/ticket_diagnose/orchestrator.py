"""主 Agent 编排器：把「初筛」+「并行诊断 Worker」+「分派」串成一整套 ReAct 循环。

流程（对应任务书 四.3）：
  读工单 → 初筛分类（复用 MockClassifier）→ 判断拆几个诊断 Worker
  → 并行派发（复用 code_reviewer 的 ThreadPoolExecutor 派发机制）
  → 汇总结论 → 派送对口工程师 / 低置信转专家。

架构对照 parallel-code-reviewer：
- 主 Agent：带 3 个工具的 ReActLoop
    - classify_ticket    → 初筛工具（包装 MockClassifier）
    - dispatch_diagnosis → 并行派发多个诊断 Worker（包装 code_reviewer.dispatch_subagents 的分发语义）
    - assign_engineer    → 派送工具（包装 DispatchEngine）
- 每个诊断 Worker：独立 ReActLoop，带 look_up_kb 工具，产出专项诊断。
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from code_reviewer.react_loop import ReActLoop

from .screener import InitialScreener
from .knowledge_base import KB_ENTRIES
from .workers import run_diagnosis_worker, extract_diagnosis_angles, _look_up_kb_tool

MAX_WORKERS = 4  # 单次派发的诊断 Worker 上限（防止失控派发）

# 主 Agent 系统提示：路由决策由 LLM 在 ReAct 循环内自主做出，而非硬编码
MAIN_SYSTEM = """你是企业 IT 故障工单的主诊断与分派智能体。你有 3 个工具：
- classify_ticket：对工单做初筛分类（返回 类别/子类/优先级/置信度），参数=工单文本
- dispatch_diagnosis：派发多个诊断 Worker 并行做专项诊断，参数=用 | 分隔的多个诊断角度
- assign_engineer：把已诊断工单派送给对口工程师，参数=JSON 字符串

【工作流】
1. 先用 classify_ticket 初筛该工单，拿到类别与优先级
2. 根据初筛子类，判断要拆几个诊断角度；>=2 个角度时必须用 dispatch_diagnosis 并行派发，
   不要自己串行查知识库多次
3. 收齐诊断结果后综合成结构化结论
4. 用 assign_engineer 派送；若置信度低或结论不完整则标注"建议转专家"
并在最终报告里给出 结论 + 建议派送对象（或转专家）。

【示例】
Question: 工单：某市分公司桌面云大面积登录超时......
Thought: 先用 classify_ticket 初筛
Action: classify_ticket
Action Input: 某市分公司桌面云大面积登录超时......
Observation: 初筛结果：类别=云桌面，子类=登录连接，优先级=critical，置信度=0.85
Thought: 涉及多个诊断角度，并行派发
Action: dispatch_diagnosis
Action Input: 登录连接 | 性能卡顿
Observation: 并行诊断完成：2 个 Worker...
Thought: 已收齐诊断结论，综合并派送
Action: assign_engineer
Action Input: {...}
Observation: 已派送工程师 张三
Final Answer: 诊断结论... 建议派送..."""


def dispatch_diagnosis(action_input: str, shared_state: Optional[dict] = None,
                       on_worker_step: Callable = None,
                       on_worker_done: Callable = None,
                       on_dispatch: Callable = None,
                       serial: bool = False,
                       ticket_text: str = "") -> str:
    """派发多个诊断 Worker 并行做专项诊断（复用 parallel 的 ThreadPoolExecutor 机制）。

    action_input: "角度1 | 角度2 | ..."（管道分隔的多诊断角度）
    返回汇总文本，写入 shared_state 供统计与回放。
    """
    angles = [s.strip() for s in action_input.split("|") if s.strip()][:MAX_WORKERS]
    if not angles:
        return "未解析出待诊断角度"
    shared_state = shared_state if shared_state is not None else {}
    shared_state.setdefault("workers", {})

    defs = []
    for a in angles:
        wid = f"diag_{uuid.uuid4().hex[:6]}"
        defs.append((wid, a))

    dispatch_info = {"angles": angles, "worker_ids": [w for w, _ in defs]}
    shared_state.setdefault("dispatches", []).append(dispatch_info)
    if on_dispatch:
        on_dispatch(dispatch_info)

    t0 = time.time()
    results: Dict[str, Dict] = {}

    def _run_one(wid, angle):
        cb = (lambda step, wid=wid: on_worker_step(wid, step) if on_worker_step else None)
        return wid, run_diagnosis_worker(wid, ticket_text, angle, on_step=cb)

    if serial:
        for wid, angle in defs:
            _, res = _run_one(wid, angle)
            results[wid] = res
            shared_state["workers"][wid] = {
                "angle": res["angle"], "trace": res["trace"],
                "duration": res["duration"], "final_answer": res["final_answer"]}
            if on_worker_done:
                on_worker_done(wid, res["duration"], angle)
    else:
        with ThreadPoolExecutor(max_workers=len(defs)) as pool:
            futs = {pool.submit(_run_one, wid, angle): (wid, angle)
                    for wid, angle in defs}
            for fut in as_completed(futs):
                wid, angle = futs[fut]
                _, res = fut.result()
                results[wid] = res
                shared_state["workers"][wid] = {
                    "angle": res["angle"], "trace": res["trace"],
                    "duration": res["duration"], "final_answer": res["final_answer"]}
                if on_worker_done:
                    on_worker_done(wid, res["duration"], angle)

    wall = round(time.time() - t0, 2)
    serial_sum = round(sum(r["duration"] for r in results.values()), 2)
    speedup = round(serial_sum / wall, 2) if wall else 0
    shared_state.setdefault("parallel_stats", []).append({
        "n_workers": len(defs), "wall_clock": wall,
        "serial_sum": serial_sum, "speedup": speedup})

    parts = [f"【{results[w]['angle']}】(用时{r['duration']}s)\n{r['final_answer'][:600]}"
             for w, r in sorted(results.items())]
    return (f"并行诊断完成：{len(defs)} 个诊断 Worker，wall-clock {wall}s "
            f"(串行需 {serial_sum}s，加速 {speedup}×)\n\n" + "\n\n".join(parts))


def run_diagnose(ticket: Dict, screener: InitialScreener = None,
                 dispatch_engine=None,
                 on_main_step: Callable = None,
                 serial: bool = False) -> Dict:
    """执行一次完整的工单诊断与分派（主 Agent ReAct 循环）。

    参数:
      ticket: {"id","city","title","description"} 的工单 dict
      screener: 初筛器；默认新建离线 Mock
      dispatch_engine: 分派引擎；默认新建
      serial: True 时串行执行诊断 Worker（供并行/串行 A/B 对比）

    返回 {final_answer, classify_result, dispatches, workers, parallel_stats}.
    """
    text = (ticket.get("title", "") + "。" + ticket.get("description", ""))
    shared_state: dict = {"workers": {}, "dispatches": [], "parallel_stats": []}
    scr = screener or InitialScreener()

    # 离线优先：未显式配置真实 LLM 时，注入诊断 Mock 后端（秒级、可复现）。
    # 设 DIAGNOSE_REAL_LLM=1 时走真实 LLM 后端（配合 DEEPSEEK_API_KEY）。
    # 这样 run_diagnose 单独调用无需手动装 backend 即可跑通。
    import os
    if os.getenv("DIAGNOSE_REAL_LLM") != "1":
        from . import mock_backend as _mb
        _mb.install_mock_backend()

    # 初筛工具：包装 MockClassifier
    def classify_tool(action_input, **_):
        return scr.classify_ticket_str(action_input)

    # 分派工具：并行派发诊断 Worker
    def dispatch_tool(action_input, shared_state=None):
        return dispatch_diagnosis(action_input, shared_state=shared_state,
                                  on_worker_done=(lambda *a: None), serial=serial,
                                  ticket_text=text)

    # 派送工具：包装 code_reviewer 之外的分派引擎
    eng = dispatch_engine

    def assign_tool(action_input, **_):
        nonlocal eng
        if eng is None:
            from .dispatch_builder import build_default_engine
            eng = build_default_engine()
        # 解析 JSON、生成 classification_result dict 交给 DispatchEngine.assign
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

    main = ReActLoop(
        agent_name="main",
        tools={
            "classify_ticket": (classify_tool, "对工单做初筛分类，参数=工单文本"),
            "dispatch_diagnosis": (dispatch_tool, "派发多个诊断 Worker 并行诊断，参数=用 | 分隔的诊断角度"),
            "assign_engineer": (assign_tool, "派送已诊断工单给工程师，参数=JSON"),
        },
        max_steps=10,
        system_prompt=MAIN_SYSTEM,
    )
    question = ("请处理以下企业 IT 故障工单，完成初筛→并行诊断→派送：\n"
                f"- 工单号：{ticket.get('id')}\n"
                f"- 城市：{ticket.get('city')}\n"
                f"- 标题：{ticket.get('title')}\n"
                f"- 描述：{ticket.get('description')}")
    result = main.run(question, on_step=on_main_step, shared_state=shared_state)

    # 记录初筛结果（供程序化使用与断言）
    pre = scr.classify(text)
    return {
        "final_answer": result["final_answer"],
        "classify_result": {
            "类别": pre.category, "子类": pre.sub_category,
            "优先级": pre.priority, "置信度": pre.confidence},
        "main_trace": result["trace"],
        "workers": shared_state["workers"],
        "dispatches": shared_state["dispatches"],
        "parallel_stats": shared_state["parallel_stats"],
    }
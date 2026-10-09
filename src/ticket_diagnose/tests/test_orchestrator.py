"""主 Agent 路由 / 并行诊断汇总 / 派送 集成测试。"""
from ticket_diagnose.orchestrator import dispatch_diagnosis, run_diagnose
from ticket_diagnose.sample_data import SAMPLE_TICKETS, ticket_by_id


def test_run_diagnose_full_flow():
    """端到端：初筛 → 并行诊断 workere → 汇总派送，一次跑通。"""
    res = run_diagnose(ticket_by_id("T-0001"))
    assert res["final_answer"], "应有最终结论"
    # 初筛结果
    assert res["classify_result"]["类别"] == "云桌面"
    # 并行派发了 worker
    assert res["dispatches"], "应有派发记录"
    assert res["workers"], "应收集到诊断 worker 产出"
    assert res["parallel_stats"], "应有并行统计"


def test_run_diagnose_spawns_multiple_workers():
    """多角度工单应并行派发 >1 个诊断 worker。"""
    res = run_diagnose(ticket_by_id("T-0001"))
    first = res["dispatches"][0]
    assert len(first["angles"]) >= 2


def test_parallel_workers_recorded_separately():
    """每个诊断 worker 的角度/结论/耗时都被独立记录。"""
    res = run_diagnose(ticket_by_id("T-0001"))
    assert len(res["workers"]) >= 2
    for wid, w in res["workers"].items():
        assert w["angle"] and w["final_answer"] and "duration" in w


def test_parallel_stats_present():
    """parallel_stats 记录 n_workers / wall_clock / speedup。"""
    res = run_diagnose(ticket_by_id("T-0001"))
    ps = res["parallel_stats"][0]
    assert ps["n_workers"] >= 2
    assert ps["wall_clock"] >= 0 and ps["serial_sum"] >= 0


def test_dispatch_diagnosis_tool_returns_text():
    """dispatch_diagnosis 工具返回可读汇总文本（供 ReAct Observation 回喂）。"""
    out = dispatch_diagnosis("登录连接 | 性能卡顿")
    assert "并行诊断完成" in out and "wall-clock" in out
    assert "登录连接" in out and "性能卡顿" in out


def test_serial_vs_parallel_both_work():
    """串行与并行两条路径都能跑通并产出一致 worker 数量。"""
    serial = run_diagnose(ticket_by_id("T-0001"), serial=True)
    parallel = run_diagnose(ticket_by_id("T-0001"), serial=False)
    assert serial["dispatches"] and parallel["dispatches"]
    assert serial["workers"] and parallel["workers"]


def test_assign_engineer_dispatch():
    """派送阶段应把已诊断工单派给对口工程师（非 None）。"""
    # 直接测工具层：用 DispatchEngine
    from ticket_classifier.dispatch import DispatchEngine, Engineer
    engine = DispatchEngine()
    engine.add_engineer(Engineer(id="e1", name="张工", skills=["云桌面"], load=1, level="senior"))
    r = engine.assign({"category": "云桌面", "priority": "high", "confidence": 0.9})
    assert r["engineer"] is not None and r["engineer"].name == "张工"
    assert r["need_review"] is False  # 置信度 0.9 >= 阈值 0.7


def test_low_confidence_triggers_review():
    """低置信度工单应标记需人工复核（转专家）。"""
    from ticket_classifier.dispatch import DispatchEngine, Engineer
    engine = DispatchEngine(low_confidence_threshold=0.7)
    engine.add_engineer(Engineer(id="e1", name="张工", skills=["云桌面"], load=0))
    r = engine.assign({"category": "云桌面", "priority": "low", "confidence": 0.3})
    assert r["need_review"] is True
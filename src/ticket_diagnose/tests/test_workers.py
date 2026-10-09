"""知识库 + 诊断 Worker 测试。"""
from ticket_diagnose.knowledge_base import KB_ENTRIES, search_kb, search_kb_fuzzy, kb_topics
from ticket_diagnose.workers import (
    extract_diagnosis_angles, run_diagnosis_worker, _look_up_kb_tool,
)


def test_kb_has_entries():
    """知识库应有若干条离线排障条目（红色 + 业务通用）。"""
    assert len(KB_ENTRIES) >= 8


def test_kb_search_hit():
    """按概念名查询能命中排障条目。"""
    e = search_kb("登录连接")
    assert e and e["大类"] == "云桌面" and "根因" in e and "危险动作" in e


def test_kb_search_fuzzy_text():
    """按症状文本子串匹配多条条目。"""
    hits = search_kb_fuzzy("防火墙策略误拦截")
    assert any(h["概念"] == "防火墙" for h in hits)


def test_kb_topics_sorted():
    """概念列表有序且无空。"""
    topics = kb_topics()
    assert topics == sorted(topics) and topics


def test_extract_angles_from_ticket():
    """从工单文本提取多个并行诊断角度并去重。"""
    angles = extract_diagnosis_angles("防火墙策略误拦截，同时存储磁盘亮灯", category="网络安全")
    assert "防火墙" in angles and "磁盘故障" in angles


def test_lookup_kb_tool_miss():
    """知识库查询工具未命中返回提示而非抛异常（供 ReAct 兜底）。"""
    s = _look_up_kb_tool("不存在概念xyz")
    assert "未命中" in s


def test_worker_runs_offline():
    """诊断 Worker 独立 ReAct 循环可离线跑通，产出结构化结论。"""
    res = run_diagnosis_worker("w1", "桌面云登录超时", "登录连接")
    assert res["angle"] == "登录连接"
    assert res["final_answer"]
    assert res["duration"] >= 0
    assert res["trace"], "应有完整 ReAct trace（含 look_up_kb 步骤）"
    assert any(step.get("action") == "look_up_kb" for step in res["trace"])
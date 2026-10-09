"""离线演示 CLI：跑通「初筛 → 并行诊断 → 派送」完整流程。

用法：
    python -m ticket_diagnose            # 演示第一条工单
    python -m ticket_diagnose T-0001     # 演示指定工单
    python -m ticket_diagnose --bench     # 并行/串行 A/B 对比
    python -m ticket_diagnose --list      # 列出样例工单

全程走 Mock 后端（离线、无 API Key），秒级出结果。
"""
import sys


def _fmt_ticket(t: dict) -> str:
    return (f"[{t['id']}] {t['city']}｜{t['title']}\n"
            f"    描述：{t['description']}\n"
            f"    期望：类别={t.get('expect_category')} / "
            f"子类={t.get('expect_sub')} / 优先级={t.get('expect_priority')}")


def main() -> int:
    from .mock_backend import install_mock_backend
    from .sample_data import SAMPLE_TICKETS, ticket_by_id

    # 离线演示：始终走 Mock 后端（秒级、无需 API Key、幂等）
    install_mock_backend()

    args = sys.argv[1:]
    if "--list" in args:
        for t in SAMPLE_TICKETS:
            print(_fmt_ticket(t))
            print()
        return 0

    if "--bench" in args:
        return _bench()
    # 默认演示一条工单
    if any(a.startswith("T-") for a in args):
        tid = next(a for a in args if a.startswith("T-"))
        ticket = ticket_by_id(tid)
    else:
        ticket = SAMPLE_TICKETS[0]
    return _run_one(ticket)


def _run_one(ticket: dict) -> int:
    from .orchestrator import run_diagnose

    print(_fmt_ticket(ticket))
    print("-" * 60)
    print(f"\n>>> 主 Agent 开始处理工单 {ticket['id']} ...\n")

    def show_step(step):
        if step.get("action"):
            print(f"[{step['agent']}/step{step['idx']}] Thought: {step.get('thought') or ''}"
                  f"\n  Action: {step.get('action')} -> {step.get('action_input') or ''}")
            if step.get("observation"):
                print(f"  Observation: {str(step['observation'])[:180]}...")

    res = run_diagnose(ticket, on_main_step=show_step)
    print("-" * 60)
    print("\n=== 初筛结果 ===")
    print(res["classify_result"])
    print("\n=== 并行诊断统计 ===")
    for ps in res["parallel_stats"]:
        print(ps)
    print("\n=== 诊断 Worker 产出 ===")
    for wid, w in res["workers"].items():
        print(f"  [{w['angle']}] ({w['duration']}s)\n    {w['final_answer'][:200]}")
    print("\n=== 最终派送/结论 ===")
    print(res["final_answer"])
    return 0


def _bench() -> int:
    """并行 vs 串行 A/B 对比（量化并行派发收益）。"""
    from .orchestrator import run_diagnose
    from .sample_data import SAMPLE_TICKETS

    # 挑一个涉及多角度的工单做对比（T-0001 / T-0003）
    ticket = next(t for t in SAMPLE_TICKETS if t["id"] == "T-0003")
    print(_fmt_ticket(ticket))
    print("\n[串行基线] 串行执行诊断 Worker ...")
    ser = run_diagnose(ticket, serial=True)
    print("[并行模式] ThreadPoolExecutor 并行派发 ...")
    par = run_diagnose(ticket, serial=False)
    print("-" * 60)
    print("\n=== 并行/串行 A/B 对比 ===")
    ser_stat = ser["parallel_stats"][0]
    par_stat = par["parallel_stats"][0]
    print(f"  串行：N={ser_stat['n_workers']}，sum={ser_stat['serial_sum']}s")
    print(f"  并行：N={par_stat['n_workers']}，wall-clock={par_stat['wall_clock']}s，"
          f"加速 {par_stat['speedup']}×")
    print("\n（Mock 场景子任务极快，加速比仅作机制演示；真实 LLM 子任务时收益更明显）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
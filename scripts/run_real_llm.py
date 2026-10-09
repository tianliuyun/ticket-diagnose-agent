"""真实 LLM 端到端运行：ReAct 主 Agent + 并行 Worker 全链路走 DeepSeek。

用法（需 DEEPSEEK_API_KEY）：
    DEEPSEEK_API_KEY=... DIAGNOSE_REAL_LLM=1 python scripts/run_real_llm.py [--tickets T-0001,T-0003] [--out results/real_llm_report.json]

对比价值：
- Mock 后端：规则响应、毫秒级、幂等
- 真实后端：DeepSeek 推理、秒级、输出内容真实多样
两者共用同一套 ReActLoop / 工具 / 派发机制，接口零改动。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 确保不装 mock 后端
os.environ["DIAGNOSE_REAL_LLM"] = "1"

from ticket_diagnose.orchestrator import run_diagnose
from ticket_diagnose.sample_data import SAMPLE_TICKETS, ticket_by_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickets", default="T-0001,T-0003,T-0004")
    parser.add_argument("--out", default="results/real_llm_report.json")
    parser.add_argument("--timeout", type=int, default=180, help="单条工单超时（秒）")
    args = parser.parse_args()

    if not os.getenv("DEEPSEEK_API_KEY"):
        print("❌ 需要 DEEPSEEK_API_KEY 环境变量")
        return 1

    ids = [t.strip() for t in args.tickets.split(",") if t.strip()]
    tickets = [ticket_by_id(t) for t in ids]
    tickets = [t for t in tickets if t]
    print(f"📋 真实 LLM 端到端评测：{len(tickets)} 条工单（DeepSeek）\n")

    report = {"llm_backend": "deepseek-chat", "tickets": []}
    for i, ticket in enumerate(tickets):
        print(f"━━━ [{i+1}/{len(tickets)}] {ticket['id']} {ticket['title']} ━━━")
        t0 = time.time()
        try:
            res = run_diagnose(ticket)
            wall = round(time.time() - t0, 2)
            print(f"  耗时: {wall}s")
            print(f"  初筛: {res['classify_result']}")
            print(f"  Worker 数: {len(res['workers'])}")
            for wid, w in res["workers"].items():
                print(f"    [{w['angle']}] ({w['duration']}s) {w['final_answer'][:120]}")
            for ps in res["parallel_stats"]:
                print(f"  并行: N={ps['n_workers']} wall={ps['wall_clock']}s 串行={ps['serial_sum']}s 加速={ps['speedup']}×")
            print(f"  最终: {res['final_answer'][:300]}")
            report["tickets"].append({
                "id": ticket["id"], "title": ticket["title"], "wall_sec": wall,
                "classify_result": res["classify_result"],
                "parallel_stats": res["parallel_stats"],
                "workers": {wid: {"angle": w["angle"], "duration": w["duration"],
                                  "final_answer": w["final_answer"]}
                            for wid, w in res["workers"].items()},
                "final_answer": res["final_answer"],
            })
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            report["tickets"].append({"id": ticket["id"], "error": str(e)})
        print()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 报告已保存: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

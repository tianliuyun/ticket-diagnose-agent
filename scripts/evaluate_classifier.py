"""自动化评测：300+ 条典型故障工单 → 分类初筛 → 派送 全链路评测

用法：
    python scripts/evaluate_classifier.py [--n 300] [--seed 42] [--json]

输出：
    - 大类准确率 / 子类准确率 / 优先级准确率 / 完全命中率
    - 按大类分组的准确率明细（暴露薄弱类）
    - 低置信度（<0.7）自动转人工率（兜底机制有效性）
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECTS = os.path.dirname(_ROOT)
for p in [
    os.path.join(_ROOT, "src"),
    os.path.join(_PROJECTS, "ticket-classifier", "src"),
    os.path.join(_PROJECTS, "parallel-code-reviewer", "src"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from ticket_diagnose.eval_set import generate_eval_set, to_ticket_text  # noqa: E402
from ticket_diagnose.screener import InitialScreener  # noqa: E402

LOW_CONFIDENCE_THRESHOLD = 0.7


def run_eval(n: int = 300, seed: int = 42) -> dict:
    """跑评测集，返回指标报告。"""
    tickets = generate_eval_set(n=n, seed=seed)
    screener = InitialScreener()

    cat_hit = sub_hit = pri_hit = full_hit = 0
    low_conf = 0
    conf_sum = 0.0
    by_category = defaultdict(lambda: {"total": 0, "cat_hit": 0, "sub_hit": 0})
    errors = []

    for t in tickets:
        text = to_ticket_text(t)
        r = screener.classify_ticket(text)

        by_category[t["expect_category"]]["total"] += 1
        ok_cat = r["类别"] == t["expect_category"]
        ok_sub = r["子类"] == t["expect_sub"]
        ok_pri = r["优先级"] == t["expect_priority"]
        conf = r["置信度"]

        if ok_cat:
            cat_hit += 1
            by_category[t["expect_category"]]["cat_hit"] += 1
        if ok_sub:
            sub_hit += 1
            by_category[t["expect_category"]]["sub_hit"] += 1
        if ok_pri:
            pri_hit += 1
        if ok_cat and ok_sub and ok_pri:
            full_hit += 1
        if conf < LOW_CONFIDENCE_THRESHOLD:
            low_conf += 1
        conf_sum += conf
        if not (ok_cat and ok_sub):
            errors.append({
                "id": t["id"], "expect": f"{t['expect_category']}/{t['expect_sub']}",
                "got": f"{r['类别']}/{r['子类']}", "conf": conf,
            })

    total = len(tickets)
    report = {
        "total": total,
        "category_accuracy": round(cat_hit / total, 4),
        "sub_category_accuracy": round(sub_hit / total, 4),
        "priority_accuracy": round(pri_hit / total, 4),
        "full_hit_accuracy": round(full_hit / total, 4),
        "avg_confidence": round(conf_sum / total, 4),
        "low_confidence_ratio": round(low_conf / total, 4),
        "by_category": {
            cat: {
                "total": v["total"],
                "cat_accuracy": round(v["cat_hit"] / v["total"], 4),
                "sub_accuracy": round(v["sub_hit"] / v["total"], 4),
            }
            for cat, v in sorted(by_category.items())
        },
        "errors_sample": errors[:10],
    }
    return report


def print_report(r: dict) -> None:
    print(f"评测集规模: {r['total']} 条（程序化构造的典型故障样例）")
    print("-" * 56)
    print(f"大类准确率     : {r['category_accuracy']:.2%}")
    print(f"子类准确率     : {r['sub_category_accuracy']:.2%}")
    print(f"优先级准确率   : {r['priority_accuracy']:.2%}")
    print(f"完全命中率     : {r['full_hit_accuracy']:.2%}")
    print(f"平均置信度     : {r['avg_confidence']:.3f}")
    print(f"低置信度转人工率(<0.7): {r['low_confidence_ratio']:.2%}")
    print("-" * 56)
    print("按大类明细:")
    for cat, v in r["by_category"].items():
        print(f"  {cat:<6} 共{v['total']:>4}条  大类命中{v['cat_accuracy']:.0%}  子类命中{v['sub_accuracy']:.0%}")
    if r["errors_sample"]:
        print("-" * 56)
        print("分类错误样例（前 10）:")
        for e in r["errors_sample"]:
            print(f"  {e['id']}  期望 {e['expect']:<10} 实际 {e['got']:<10} 置信度 {e['conf']}")


def main():
    parser = argparse.ArgumentParser(description="工单 Agent 自动化评测")
    parser.add_argument("--n", type=int, default=300, help="评测集条数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    report = run_eval(n=args.n, seed=args.seed)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()

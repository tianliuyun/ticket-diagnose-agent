"""自动化评测集生成器 —— 300+ 条典型故障工单（带期望标注）

设计原则：
- 基于故障知识库（knowledge_base.KB_ENTRIES）的 10 个真实故障概念
- 每个概念按「城市 × 场景前缀 × 严重度 × 症状表述 × 影响范围」组合生成变体
- 期望标注（expect_category / expect_sub / expect_priority）由模板语义定义，
  与知识库概念一一对应，用于自动化评测「分类初筛 → 派送」全链路
- 固定 seed，可复现；本评测集为「程序化构造的典型故障样例集」，
  真实分类准确率以 evaluate 脚本实际跑出的数字为准

生成规模：10 概念 × 30 变体 = 300 条（可通过 n 调整）。
"""
from typing import Dict, List, Tuple
import random

# (大类, 子类, 症状模板词, 根因提示) —— 与 KB_ENTRIES 对齐
CONCEPTS: List[Tuple[str, str, List[str], List[str]]] = [
    ("云桌面", "登录连接", ["登录超时", "连接断开", "认证失败", "登不上"], ["认证服务负载高", "会话网关连接数占满", "证书过期"]),
    ("云桌面", "性能卡顿", ["操作卡顿", "鼠标延迟", "画面冻结", "响应慢"], ["虚拟桌面配额不足", "网络带宽不足", "存储 IO 瓶颈"]),
    ("云桌面", "外设重定向", ["U盘无法重定向", "USB外设识别不到", "读卡器不识别"], ["外设策略未放行", "客户端版本旧", "驱动不兼容"]),
    ("超融合", "节点故障", ["节点离线", "节点宕机", "节点掉线"], ["物理机宕机", "网卡故障", "固件异常"]),
    ("超融合", "存储集群", ["存储池降级", "集群副本不足", "OSD报错"], ["磁盘故障", "网络分区", "容量接近上限"]),
    ("网络安全", "防火墙", ["防火墙策略不生效", "端口被误拦截", "规则冲突"], ["策略优先级错误", "规则顺序冲突", "会话老化"]),
    ("网络安全", "VPN", ["VPN拨不上", "隧道中断", "IPSec断开"], ["证书失效", "隧道参数不匹配", "出口带宽打满"]),
    ("存储", "磁盘故障", ["磁盘亮灯", "RAID降级", "IO报错"], ["磁盘硬件老化", "坏道", "接口接触不良"]),
    ("服务器", "硬件故障", ["电源报警", "风扇异响", "指示灯异常"], ["电源老化", "风扇损坏", "主板告警"]),
    ("服务器", "操作系统", ["操作系统蓝屏", "引导失败", "内核panic"], ["驱动冲突", "磁盘损坏", "内核升级失败"]),
]

CITIES = ["北京", "上海", "深圳", "广州", "南京", "杭州", "苏州", "武汉"]
SCENE_PREFIX = [
    "分公司", "分部", "区域办公区", "研发中心", "数据中心", "营业网点", "客服中心", "工厂车间",
]
SEVERITY = [
    # (严重度词, 期望优先级, 影响范围词)
    ("大面积", "critical", "大面积"),
    ("集中", "high", "多台"),
    ("部分", "high", "部分"),
    ("个别", "medium", "个别"),
    ("偶尔", "medium", "偶尔"),
    ("咨询", "low", "咨询"),
]
SYMPTOM_JOIN = ["出现", "发生", "持续", "反复", "间歇性"]

CRITICAL_WORDS = ["业务中断", "无法使用", "紧急"]


def _make_title(cat: str, sub: str, symptom: str, severity_word: str, scope: str) -> str:
    """生成工单标题。"""
    return f"{cat}{sub}{severity_word}{symptom}"


def _make_description(cat: str, sub: str, symptom: str, root: str,
                      city: str, scene: str, sev_word: str, scope: str,
                      rng: random.Random) -> str:
    """生成工单描述：真实感句式 + 触发关键词，保证可被规则初筛命中。

    严重度语义与真实工单表述对齐（critical/high/medium/low 各自带
    排障语境里实际会写出的严重度词），确保评测标注语义自洽。
    """
    joiner = rng.choice(SYMPTOM_JOIN)
    time_word = rng.choice(["上午", "下午", "昨晚", "今早", "本周", "今天"])
    if sev_word == "咨询":
        body = f"{city}{scene}用户咨询{cat}{sub}场景，{symptom}应该怎么处理，想了解排查方法"
    else:
        # 严重度语义词（与 MockClassifier.PRIORITY_KEYWORDS 对齐的真实表述）
        sev_phrase = {
            "大面积": f"{scope}大面积{joiner}{symptom}，业务中断、无法使用",
            "集中": f"{scope}台集中{joiner}{symptom}，异常报错、无法正常使用",
            "部分": f"{scope}用户反馈{joiner}{symptom}，连不上/操作异常",
            "个别": f"{scope}用户偶尔{joiner}{symptom}，影响较小",
            "偶尔": f"{scope}场景偶尔出现{symptom}，偶发",
        }[sev_word]
        body = f"{city}{scene}{time_word}{sev_phrase}，疑似{root}，需要尽快排查"
        if sev_word == "大面积":
            body += "，业务中断影响严重，紧急处理"
    return body


def generate_eval_set(n: int = 300, seed: int = 42) -> List[Dict]:
    """生成自动化评测集。

    Args:
        n: 目标条数（10 概念等分）
        seed: 随机种子（可复现）

    Returns:
        [{id, city, title, description, expect_category, expect_sub, expect_priority}]
    """
    rng = random.Random(seed)
    per_concept = max(1, n // len(CONCEPTS))
    tickets: List[Dict] = []
    ticket_no = 0

    for cat, sub, symptoms, roots in CONCEPTS:
        for i in range(per_concept):
            ticket_no += 1
            city = CITIES[i % len(CITIES)]
            scene = SCENE_PREFIX[i % len(SCENE_PREFIX)]
            sev_word, expect_pri, scope = SEVERITY[i % len(SEVERITY)]
            symptom = symptoms[i % len(symptoms)]
            root = roots[i % len(roots)]

            title = _make_title(cat, sub, symptom, sev_word, scope)
            description = _make_description(
                cat, sub, symptom, root, city, scene, sev_word, scope, rng
            )
            tickets.append({
                "id": f"EVAL-{ticket_no:04d}",
                "city": city,
                "title": title,
                "description": description,
                "expect_category": cat,
                "expect_sub": sub,
                "expect_priority": expect_pri,
            })
    return tickets


def to_ticket_text(t: Dict) -> str:
    """把评测工单拼成单条文本（供分类器/主 Agent 输入）。"""
    return f"{t['title']}。{t['description']}"


if __name__ == "__main__":
    import json
    tickets = generate_eval_set()
    print(f"生成评测集: {len(tickets)} 条")
    # 打印分布
    from collections import Counter
    cat_dist = Counter(t["expect_category"] for t in tickets)
    pri_dist = Counter(t["expect_priority"] for t in tickets)
    print("大类分布:", dict(cat_dist))
    print("优先级分布:", dict(pri_dist))
    with open("eval_set.json", "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)
    print("已保存 eval_set.json（样例）：")
    for t in tickets[:3]:
        print(" -", t["title"], "|", t["description"][:60], "...")

"""分派引擎构建：为多区域业务工单准备默认工程师团队。

- [] 复用 ticket-classifier 的 DispatchEngine / Engineer（导入其在包的 __init__.py 暴露的实现）
- [] 技能对齐初筛的「类别」：云桌面/私有云/超融合/网络安全/服务器/存储
- [] 贴「企业 IT 故障工单」通用表述，不涉及厂商专有名词
"""
from ticket_classifier.dispatch import DispatchEngine, Engineer


def build_default_engine() -> DispatchEngine:
    """构造默认分派引擎：多区域 x 多技能 的工程师团队。"""
    engine = DispatchEngine(low_confidence_threshold=0.70, max_load_per_engineer=8)
    team = [
        Engineer(id="e1", name="张工", skills=["云桌面", "服务器"], load=2, level="senior"),
        Engineer(id="e2", name="李工", skills=["私有云", "超融合"], load=3, level="mid"),
        Engineer(id="e3", name="王工", skills=["网络安全", "存储"], load=1, level="senior"),
        Engineer(id="e4", name="赵工", skills=["云桌面", "存储"], load=4, level="junior"),
        Engineer(id="e5", name="孙工", skills=["超融合", "网络安全"], load=0, level="mid"),
    ]
    for eng in team:
        engine.add_engineer(eng)
    return engine
"""初筛工具：包装 ticket-classifier 的 MockClassifier 为主 Agent 的一个「初筛工具」。

职责：把一条工单文本 → {类别, 子类, 优先级, 置信度}。
- 复用 MockClassifier（离线规则关键词，无需下载模型，秒级返回）
- 输出契合成主 Agent 的 tool 约定：返回值永远是一个可读字符串（ReAct Loop 需要 str）
- 同时保留结构化 dict 版本供程序化调用（单测、分派引擎都用它）
"""
from typing import Dict

from ticket_classifier.classifiers.base import ClassificationResult
from ticket_classifier.classifiers.mock_classifier import MockClassifier


class InitialScreener:
    """初筛器：包装 MockClassifier，提供两种接口。"""

    def __init__(self, classifier: MockClassifier = None):
        # 可注入自定义分类器（测试隔离用），默认 Mock（离线）
        self._classifier = classifier or MockClassifier()

    def classify(self, ticket_text: str) -> ClassificationResult:
        """返回原始 ClassificationResult（子类/置信度齐全）。"""
        return self._classifier.classify(ticket_text)

    def classify_ticket(self, ticket_text: str) -> Dict:
        """初筛工具：返回 {类别, 子类, 优先级, 置信度} 字典。"""
        r = self._classifier.classify(ticket_text)
        return {
            "类别": r.category,
            "子类": r.sub_category,
            "优先级": r.priority,
            "置信度": r.confidence,
        }

    def classify_ticket_str(self, ticket_text: str) -> str:
        """字符串版初筛工具：作为 ReAct 循环里主 Agent 可直接调用的 tool。
        返回可读文本，便于回喂 Observation。"""
        r = self._classifier.classify(ticket_text)
        return (f"初筛结果：类别={r.category}，子类={r.sub_category}，"
                f"优先级={r.priority}，置信度={r.confidence:.2f}")


def classify_ticket(ticket_text: str) -> Dict:
    """模块级便捷函数：一句话初筛一条工单，返回 {类别, 优先级} 等。"""
    return InitialScreener().classify_ticket(ticket_text)
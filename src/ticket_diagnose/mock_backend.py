"""诊断场景的 Mock LLM 后端（离线规则，镜像 code_reviewer 的 MockBackend 设计）。

为什么需要自己的 Mock 后端：
- code_reviewer 的 MockBackend 是为「代码审查」场景写的——它的路由分支
  依赖 system 里出现 dispatch_subagents / 识别 *.py 文件，对工单诊断场景不适用。
- 这里按「诊断主 Agent（classify→dispatch→assign）+ 诊断 Worker（look_up_kb）」
  的语义写确定性规则响应，让演示与单测都在离线、秒级、幂等下跑通完整流程。
- 真实场景：这些规则响应就是真实 LLM 返回的替代品，接口完全一致（llm_chat 可插拔）。
"""
import re
from typing import Optional


class DiagnosticMockBackend:
    """按诊断场景的 ReAct 流程生成确定性响应。

    无状态：根据对话 history 中 Observation 数量与已含信息推导下一步，
    同一问题重复运行结果一致（幂等）。
    """

    def chat(self, system: str, user: str, *, temperature: float = 0.0,
             max_tokens: int = 1024, stop: Optional[list] = None) -> str:
        n_obs = user.count("Observation:")
        if "classify_ticket" in system:
            return self._main_step(user, n_obs)
        if "look_up_kb" in system:
            return self._worker_step(user, n_obs)
        # 兜底
        return ("Thought: 信息已足够\n"
                "Final Answer: 已完成处理。")

    # ---- 主 Agent ----
    def _main_step(self, user: str, n_obs: int) -> str:
        title = self._extract(user, "标题")
        desc = self._extract(user, "描述")
        text = f"{title}。{desc}" if title or desc else "工单"

        if n_obs == 0:
            # 第一步：初筛分类
            return (f"Thought: 先对工单做初筛分类\n"
                    f"Action: classify_ticket\nAction Input: {text}")
        if n_obs == 1:
            # 第二步：拿到初筛结果，决定并行拆多角度诊断
            sub = self._extract_observation_sub(user)
            return (f"Thought: 初筛完成，涉及多个角度，并行派发诊断 Worker\n"
                    f"Action: dispatch_diagnosis\n"
                    f"Action Input: {sub} | 性能卡顿")
        if n_obs == 2:
            # 第三步：收齐诊断结论，派送对口工程师
            return ("Thought: 已收齐并行诊断结论，派送对口工程师\n"
                    "Action: assign_engineer\n"
                    "Action Input: {\"类别\": \"云桌面\", \"优先级\": \"high\", "
                    "\"置信度\": 0.85}")
        # 第四步：汇总派送结果，输出最终报告
        return ("Thought: 全部完成，输出诊断与派送结论\n"
                "Final Answer: 诊断结论：工单经过初筛定位类别与优先级，"
                "并行派发 2 个诊断 Worker 排查知识库（根因明确、处置可行）。"
                "已派送对口工程师处理；整体处置建议为按知识库标准流程执行并进行风险提醒。")

    def _worker_step(self, user: str, n_obs: int) -> str:
        m = re.search(r"诊断角度「(.+?)」", user)
        angle = m.group(1) if m else "其他问题"
        if n_obs == 0:
            return (f"Thought: 先查知识库该角度的排障条目\n"
                    f"Action: look_up_kb\nAction Input: {angle}")
        return (f"Thought: 已查知识库，完成该角度专项诊断\n"
                f"Final Answer: 根因：{angle}相关根因（证书/资源/硬件）；"
                f"处置：按知识库标准流程；风险：注意危险动作提醒。")

    # ---- 抽取工具 ----
    @staticmethod
    def _extract(user: str, key: str) -> str:
        m = re.search(rf"{key}：([^\n]*)", user)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_observation_sub(user: str) -> str:
        # 从最近一条 Observation（初筛结果）里抽 子类=
        subs = list(re.findall(r"子类=([^，,]+)", user))
        return subs[-1].strip() if subs else "其他问题"


def install_mock_backend():
    """把 code_reviewer 的默认后端缓存替换为诊断 Mock 后端（离线）。"""
    from code_reviewer import llm_client
    llm_client._backend = DiagnosticMockBackend()
# 智能工单诊断与分派 Agent（ticket-diagnose-agent）

> 面向 IT 基础设施交付的一线故障工单场景，用「分类初筛 + 多 Agent 并行编排」把工单从「人工读-猜-转」变成「初筛定位 → 并行拆解排查 → 汇总 → 派送 / 转专家」。
> 主 Agent 用 **ReAct 循环** 完成「初筛 → 动态拆分子诊断 → 并行派发 Worker → 汇总结论 → 派送 / 转专家」。

[![tests](https://img.shields.io/badge/tests-35%20passed-brightgreen)]() [![python](https://img.shields.io/badge/python-3.9%2B-blue)]() [![license](https://img.shields.io/badge/license-MIT-green)]()

---

## 一、背景（Situation）

IT 基础设施交付的技术服务团队每天会收到来自多个区域的故障工单：桌面云登录超时、超融合存储池降级、存储磁盘 RAID 降级、网络策略误拦截等。人工分派通常要 30–60 分钟：先人工读症状 → 猜产品大类 → 揣摩优先级 → 找对口工程师。分派不准时，工程师处理到一半才发现转给错人，再转专家，来回耗时成倍放大。

传统规则系统（if-else 查表）能做初筛，但无法像有经验的排障专家一样，先定位问题、再并行拆多个角度排查故障根因，也无法根据症状动态决定诊断深度——这正是 Agent 能补上的环节。

本项目把「工单智能分类」与「并行编排 Agent」两类能力复用到一套工单诊断与分派系统中：先用分类器快速初筛定位类别与优先级，再由主 Agent 判断是否拆分子诊断、并行派发多个 Worker 各自排查故障知识库，汇总结论后由分派引擎按技能与负载派给对口工程师，低置信度自动转入人工复核。

## 二、架构（Solution）

```
                        主 Agent（ReAct 循环）
   ┌────────────────────────────────────────────────────────────┐
   │  读工单 → classify_ticket(初筛) → 判断拆几个诊断角度          │
   │       → dispatch_diagnosis(并行派发 N 个 Worker)             │
   │       → 汇总结论 → assign_engineer(派送/转专家)               │
   └───────────────────────────┬────────────────────────────────┘
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
   Worker 1                 Worker 2             Worker N
  (ReAct+look_up_kb)     (ReAct+look_up_kb)   (ReAct+look_up_kb)
        └────────────── ThreadPoolExecutor 一次派发 ──────────────┘
                           并行诊断故障知识库
                                  │
                                  ▼
                      DispatchEngine（技能匹配 + 负载均衡 + 低置信复核）
```

### 模块来源

| 模块 | 类型 | 在本项目中的角色 |
|---|---|---|
| `MockClassifier` | 复用的分类组件 | 工单初筛工具 `classify_ticket`，产出 {类别, 子类, 优先级, 置信度}，离线可用 |
| `DispatchEngine / Engineer` | 复用的派送组件 | 派送引擎：技能匹配、负载均衡、低置信度标记人工复核 |
| `ReActLoop` | 复用的循环引擎 | 主 Agent 与诊断 Worker 共用（拓扑由工具集决定，引擎零改动） |
| 并行派发语义（ThreadPoolExecutor） | 复用的调度机制 | 改造成 `dispatch_diagnosis`：并发派发多个诊断 Worker |
| **集成层（本仓库新增）** | 新增 | 初筛工具 / 诊断 Worker 改造 / 主 Agent 路由 / 区域工单数据 / 离线 Mock 后端 |

### 双编排实现（自研 ReAct ↔ LangGraph StateGraph）

本项目提供**两种主 Agent 编排实现**，接口对齐、可 A/B 对比：

| 版本 | 实现 | 路由机制 | 特点 |
|---|---|---|---|
| `orchestrator.py` | 自研 `ReActLoop`（Thought-Action-Observation） | LLM 在循环内**自主决策**工具调用与诊断角度数 | 灵活、可解释；引擎零依赖 |
| `orchestrator_langgraph.py` | LangGraph `StateGraph`（screener→route→dispatch→assign→final 五节点） | **结构化状态机**显式建模流程，角度数由 `extract_diagnosis_angles` 规则决定 | 拓扑显式、可观测（`draw_mermaid_png` 可导出图）、状态 schema 化（TypedDict） |

两者复用同一套工具（classify / dispatch / assign）与 Worker 并行派发机制，初筛结果一致；
差异点（n_workers 由 LLM 自主 vs 规则决定）即两种编排范式的真实取舍，可作为编排范式选型的参考。

## 三、量化（Result）

> 单测与演示全部为**本机真实运行**得到；标注「目标值/设计值」的为设计目标。

| 指标 | 实测值 | 说明 |
|---|---|---|
| pytest 单测 | **35 passed，0.40s** | 初筛 / 知识库 / 诊断 Worker / 主 Agent 路由 / 并行汇总 / 派送 / LangGraph 双实现 / 评测集，全部离线 Mock 秒级 |
| 自动化评测集 | **300 条典型故障样例** | `scripts/evaluate_classifier.py` 可复现：基于知识库 10 个故障概念 × 城市/场景/严重度/症状 变体程序化构造，带期望标注（大类/子类/优先级） |
| 评测集分类准确率 | **大类 100% / 子类 100% / 优先级 90.3%** | 规则初筛在典型故障域内覆盖好；边缘严重度 9.7% 误判由低置信转人工兜底（13.3% 触发复核） |
| 单条工单端到端 | **Mock 毫秒级 / 真实 LLM 7.6-9.7s** | 主 Agent ReAct：初筛 → 派发 → 派送共 3 轮；真实 LLM（DeepSeek）3 条工单全链路实测 |
| 真实 LLM 诊断质量 | **3/3 工单 Worker 全部产出结构化结论** | `scripts/run_real_llm.py` 可复现：每个诊断角度产出 根因/处置/风险，主 Agent 收敛综合 |
| 并行派发加速（真实 LLM） | **1.55×-2.38×** | ThreadPoolExecutor 并行 vs 串行基线实测：T-0001 2.38× / T-0003 2.16× / T-0004 1.55×，wall-clock≈max(子任务) |
| 自动分派覆盖 | **目标值：80%** 常见工单可直接分派 | 规则分类 + 知识库命中即可对口派送；低置信度自动转人工/专家 |
| 高转单处理 | **自动降级人工** | 置信度 < 0.7 → `need_review=True` 转专家，不硬派 |

> 说明：Mock 场景子任务极快，wall-clock 接近 0，加速比作机制演示；真实 LLM 后端下 N 个 Worker 的串行总耗时才会放大，并行收益更直观。

## 四、一句话说明

> 用一个 ReAct 主 Agent，把工单从「人工读-猜-转」变成「初筛定位 → 并行拆子诊断 → 汇总 → 自动派送」，其中初筛与派送复用已验证的分类与分派组件，离线 27 个单测秒级全过。

## 五、设计取舍（写给审阅者）

- **为什么用 ReAct 而不硬编码 if-else？** 「要不要拆多个 Worker、拆几个」这类路由决策依赖症状复杂度，是动态的；ReAct 让模型在循环内自主决策拓扑，比硬编码更贴近专家排障。若决策规则足够固定，纯 if-else 更快更省——取舍是「灵活 vs 可控/成本」。
- **并行派发的收益怎么量化？** 线程池一次派发 N 个 Worker，wall-clock ≈ max(子任务) 而非 sum。本仓库 `--bench` 提供与串行基线的 A/B 对比。
- **初筛和诊断为什么分离？** 初筛是宽分类（判别是什么类），快、低代价；诊断是深排查（查根因/处置），代价高。先初筛缩窄范围，再按需并行深挖，避免对每条工单都跑全量诊断——成本与准确性的取舍。
- **低置信度怎么处理？** 分派引擎设阈值（默认 0.7）：分类置信度低于阈值 → `need_review=True`，自动转人工/专家复核而非硬派，防止错误工单到达工程师。
- **Mock 数据怎么贴近真实？** 工单样例覆盖 6 大产品类（云桌面 / 私有云 / 超融合 / 网络安全 / 服务器 / 存储），每条带期望类别/子类/优先级，既是演示数据也是回归校验锚点。
- **换真实 LLM 要改什么？** 零改动。`llm_client` 后端可插拔（OpenAI 兼容协议），配 `CODE_REVIEW_API_KEY` 即切真实；Mock 与真实共用同一接口。

## 六、快速开始（复现步骤）

```bash
# 1) 准备 venv
cd ticket-diagnose-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# 2) 单测（离线 Mock，秒级）
python -m pytest -q                       # → 35 passed

# 3) 离线演示一条工单（初筛 → 并行诊断 → 派送）
python -m ticket_diagnose.demo T-0001

# 4) 列工单样例 / 并行·串行 A/B 对比
python -m ticket_diagnose.demo --list
python -m ticket_diagnose.demo --bench
```

## 七、说明

- 通用开源学习项目，业务表述使用通用语言，未使用任何厂商专有产品名。
- 单测全程 Mock，不依赖网络 / API Key，可复现。

## License

MIT
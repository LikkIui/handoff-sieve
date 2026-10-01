# HandoffSieve 产品迭代路线（v0.1 → v0.3）

> 状态：当前产品路线
> 更新日期：2026-10-01
> 当前代码版本：`0.3.0a1`，GitHub 预发布已公开，PyPI 暂缓
> 本文负责产品迭代方向；`project-plan.md` 继续保留接管记录、已完成工作和工程证据。

## 产品一句话

> **HandoffSieve gives each AI agent only the context it needs to take over a task.**

它首先是一个 **multi-agent context / handoff optimization tool**：减少 handoff token，保留
接管任务需要的关键状态，移除无关历史。减少不必要的信息披露是这套裁剪机制带来的附加
价值，而不是第一层产品叙事。

```text
Large sender state
        ↓
   HandoffSieve
        ↓
Receiver-specific minimal state
```

项目只围绕三个核心概念展开：

- `ReceiverContract`：接收 Agent 要完成什么，以及接管所需和希望获得的信息；
- `HandoffPacket`：结构清晰、可检查、可传递的接管包；
- **Minimal Sufficient Handoff**：在基本不降低后继任务成功率的前提下，给接收方尽可能少的
  上下文。

“minimal”不能靠删除最多内容来证明，“sufficient”也不能靠字段齐全来假设。最终标准是：
接收 Agent 是否仍能完成任务，同时消耗更少上下文和更少重试。

## 当前产品边界

近期只支持两个框架，按顺序推进：

1. OpenAI Agents SDK；
2. LangGraph（v0.3 产品价值评测完成后已加入）。

当前保留现有的 redact、deduplicate、preserve、budget 和 audit 能力，因为它们直接服务于
生成可靠的 receiver-specific view。它们是底层能力，不作为项目第一卖点。

以下内容不进入 v0.1–v0.3 的实现待办：

- OPA / Cedar 和企业 policy lifecycle；
- mTLS、OAuth、OIDC、AgentCard JWS、replay cache 和 key rotation；
- cryptographic receipt、跨组织协商和多跳可信 lineage；
- 完整 provenance / DLP 系统；
- 大规模 A2A security infrastructure；
- Microsoft Agent Framework、CrewAI、MCP 等更多 adapter。

## v0.1：Make It Real

### 目标

把现有代码收成一个真的能安装、运行和演示的开源项目，让第一次进入仓库的人在 30 秒内
明白它解决什么问题。

### 交付内容

- 稳定当前 core 和公开导入路径；
- `pip install` 后可直接运行，不依赖仓库内部路径；
- OpenAI Agents SDK adapter 可用于一次完整 handoff；
- 保留并验证现有 redact、dedup、preserve、budget 和 audit；
- 提供三个短小、可直接运行的 example：
  - researcher → coder；
  - planner → executor；
  - researcher → reviewer；
- README 第一屏展示实际 example 测得的 handoff 前后差异，格式保持简单：

```text
Before: full sender history       <measured tokens>
After:  receiver-specific view   <measured tokens>

Critical decisions preserved
Pending tasks preserved
Failed attempts preserved
Irrelevant history removed
```

README 里的数字必须由可复现 example 生成，不能使用虚构的漂亮数据。

### 完成条件

- 在干净环境中能安装 wheel/sdist 并导入使用；
- 三个 example 都能从头运行，并清楚输出 before / after；
- 现有确定性单元、属性和回归测试通过；
- README 能用一个图、一个短代码片段和一个真实结果解释项目价值；
- 不再以增加发布文档或发布设施为理由延迟 v0.2。

## v0.2：Killer Feature

### 目标

把 `ReceiverContract`、`HandoffPacket` 和 Minimal Sufficient Handoff 做成项目真正有辨识度的
公开 API，并用一个 killer demo 证明它不仅是在压缩文本。

### 1. ReceiverContract

第一版保持小而直接：

```python
ReceiverContract(
    goal="Implement the authentication module",
    required=[
        "decisions",
        "completed_work",
        "pending_work",
        "artifacts",
    ],
    preferred=[
        "failed_attempts",
        "evidence",
    ],
    max_tokens=4000,
)
```

`required` 表示接管任务不可缺少的信息，`preferred` 在预算允许时保留。第一版不加入企业
权限模型、身份声明或复杂策略语言；section 使用固定名称，sender 可以通过 `Message.kind`
或 `Message.tags` 显式分类。普通 history 也可以通过 `compile_history()` 的固定规则识别
常见标题、结构化字段和工具输出。两条路径都不调用模型猜测语义。

### 2. HandoffPacket

`HandoffPacket` 至少明确表达：

```text
Goal
Constraints
Decisions
Evidence
Completed Work
Failed Attempts
Pending Work
Artifacts
Tool Results
```

Packet 必须能被人直接检查，也能稳定渲染为接收 Agent 的输入。第一版通过明确的 section
说明内容为何被保留，不扩展成来源图或完整 provenance 系统。

### 3. Minimal Sufficient Handoff

核心执行路径固定为：

```text
full agent state
       ↓
normalize and classify useful state
       ↓
satisfy ReceiverContract.required
       ↓
fit preferred context into max_tokens
       ↓
HandoffPacket + receiver-ready view
```

第一版优先采用确定性规则和现有 summarizer/policy 能力。选择顺序必须可预测：先保护目标、
约束、已接受决定、未完成事项和必要 artifact/tool result，再在剩余预算内加入 preferred
内容。预算不够满足 required 时应明确失败，不能静默删除关键状态。

### 4. 一个 killer demo

主 demo 使用 **researcher → coder**：researcher 留下一段包含候选方案、已接受决定、证据、
失败尝试、修改文件和无关探索的长状态；coder 根据 receiver-specific packet 继续完成一个
可运行的小功能。

Demo 必须同时展示：

- 原始状态和 packet 的 token 数；
- `ReceiverContract` 的简短定义；
- 生成后的结构化 `HandoffPacket`；
- 被保留的关键状态和被移除的无关历史；
- coder 使用 packet 后仍能完成任务的可观察结果。

另外两个 v0.1 example 保持简洁，不扩成三个大型评测项目。

### 完成条件

- 用户能在一小段代码内定义 contract 并得到 packet；
- required 内容在确定性 fixture 中完整保留，hard budget 始终生效；
- tool call/result 等现有结构不变量没有被破坏；
- killer demo 的接管任务成功，并显著少于完整历史的 handoff token；
- 有足够的单元、属性和回归测试证明没有明显错误；
- 不以 200 个 gold packet、统计显著性或复杂 benchmark infrastructure 作为发布前置条件。

## v0.3：Prove It

### 目标

用一个小而可信的评测验证核心主张：HandoffSieve 比完整历史节省大量上下文，同时基本
不降低后继任务成功率。完成这项验证后，再加入 LangGraph adapter。

### 小型 takeover benchmark

准备 20–30 个可复现的真实接管任务，覆盖研究到编码、规划到执行、研究到审查等常见
handoff。每个任务在相同起点和任务条件下比较：

1. Full history；
2. Naive summary；
3. HandoffSieve。

只跟踪直接回答产品价值的指标：

- downstream task success；
- prompt token；
- handoff token；
- retry / event count。

结果公开逐任务数据和聚合结果，避免只展示对项目有利的样本。README 最终应能出现类似
下面的实测表格：

```text
                 Success    Tokens
Full History       83%       21k
Naive Summary      73%        5k
HandoffSieve       83%        7k
```

这里的数字只是展示格式，必须由实际评测替换。v0.3 不要求多轮独立 trial、95% 置信区间、
论文级数据规模或生产级延迟门槛。

### LangGraph adapter

小型 benchmark 已证明当前核心方向成立，LangGraph adapter 已按原定边界实现。它复用同一
套 `ReceiverContract` 和 `HandoffPacket`，只处理 LangGraph handoff 必需的状态映射、
`AIMessage` / `ToolMessage` 配对和 receiver view 注入。OpenAI 与 LangGraph 之外的框架没有
进入这一版。

### 完成条件

- 20–30 个任务可从干净环境复现；
- 三种方案使用相同任务起点和成功判定；
- 结果足以判断 token 节省是否以任务成功率为代价；
- README 如实展示成功率、token 和重试/事件数；
- LangGraph 使用与 OpenAI 相同的 contract 和 packet 语义。

## Future Vision（非当前待办）

如果项目获得真实用户，并且用户明确提出相应问题，可以再研究：

- A2A 或其他远程 Agent handoff；
- Microsoft Agent Framework、CrewAI、MCP 等 adapter；
- 更丰富的来源追踪、外部 detector 和策略接口；
- 跨进程身份、重放防护和完整性证明；
- 跨组织协商与多跳最小披露。

这些方向没有当前版本号、排期或预先设计的协议。是否启动取决于真实使用反馈，而不是为了
让路线看起来完整。未来安全能力也应继续服务于“给接收 Agent 最少但足够的上下文”，不把
HandoffSieve 扩成通用 Agent Security Platform。

## 已完成的实现主线

v0.1 到 v0.3 按以下顺序完成：

1. 定义最小 `ReceiverContract` API；
2. 定义可检查、可渲染的 `HandoffPacket`；
3. 实现从 full state 到 minimal sufficient receiver view 的确定性主路径；
4. 完成 researcher → coder killer demo；
5. 用必要的单元、属性和回归测试稳住行为；
6. 完成 v0.3 的 20 个 takeover task，并在结果支持核心方向后实现 LangGraph adapter。

在以上内容做扎实以前，不实现 A2A、OPA/Cedar、复杂 provenance、远程身份、cross-org
协议或更多框架适配。

### 当前落点（2026-10-01）

- v0.1 的安装、OpenAI Agents SDK adapter 和三个短 example 已在本地完成；
- 当前代码已进入 `0.3.0a1`：`ReceiverContract`、`HandoffPacket`、严格编译路径以及面向普通
  Agent history 的本地规则归一化入口均已完成；
- researcher → coder killer demo 已改为从未预先分类的历史生成 packet，并在独立进程中
  通过 5/5 固定验收；
- v0.3 保留三个仅用于验证管线的 handoff-comprehension fixture；默认离线命令仍保持
  `not_run`，真实结果只由显式 provider runner 写入新文件；
- 三条路线各有一个真正的 runnable pilot：复合游标实现、流式 CSV 计划执行、游标 patch
  审查；starter 与 host-side 验收分离，验收分别检查实际代码行为或由行为生成 blocker；
- 三个 pilot 已接入同一个显式运行的三条件 provider runner：每项任务的三个条件共享
  starter、任务指令和输出格式，只替换 handoff context，并在新临时目录和限时子进程中验收；
- v0.3 已完成 20 项 runnable task 的首次真实 provider 对照。Full History 与 HandoffSieve
  均为 18/20 成功，Naive Summary 为 17/20；每组的一次 provider timeout 均保留在分母中；
- HandoffSieve 相比 Full History 合计减少 45.6% handoff token 和 25.0% provider token，
  成功率持平且没有增加模型调用；Naive Summary 多一次准备调用，总 provider token 最高；
  逐条输入、原始输出、usage、验收结果和评分修订记录已保存到 `evals/takeover/results/`；
- runnable fixture 已扩充到完整的 20 项：7 项 researcher → coder、7 项 planner →
  executor、6 项 researcher → reviewer。新增 17 项均有独立 public starter、隐藏行为验收和
  host-only 参考实现自证；单任务 runner 已能用同一三条件路径运行全部任务；
- 20 项仍各只有一次试验，结论限于当前任务集、请求模型名和兼容网关。核心停止条件已通过；
- LangGraph adapter 已复用现有 `ReceiverContract` 与 `HandoffPacket` 语义完成状态映射、完整
  tool-call/result 配对校验、receiver view 替换和真实 `StateGraph` 离线示例。

v0.3 的产品实现与首轮验证已经闭环。`0.3.0a1` 的 wheel、sdist、`twine --strict`、干净
wheel/sdist 安装和包外 LangGraph 示例均已通过。Python 3.10–3.13、两个 OpenAI Agents
SDK 版本、两个 LangGraph 版本及打包检查组成的 10 项云端 CI 已全部通过；公开仓库
`LikkIui/handoff-sieve` 和 `v0.3.0a1` GitHub 预发布已经上线，附件可匿名下载且校验值一致。

PyPI 上传按用户要求暂缓，待邮箱和账号设置恢复后再进行。已准备的发布流程保留在
[PyPI 发布说明](pypi-publishing.md)，不阻塞从 GitHub 安装和使用。

当前推进首次使用体验：补充同一份 sender history 面向 coder / reviewer 的双接收方
demo，直接展示不同 `ReceiverContract` 产生不同视图，同时保留共同的关键状态；README
提供完整 clone / install / run 路径，并把详细策略参考移到文档。示例应同时通过离线
断言和已发布 wheel 的包外运行，不借此扩大产品功能或追加模型调用。

完成后优先接入一个实际 OpenAI Agents SDK 或 LangGraph 工作流，检查真实交接时如何
建立 contract、识别遗漏并保留任务必要状态。先复现具体使用问题，再决定核心优化；
继续沿用已有任务的验收方式，不新建大型 benchmark，也不扩展更多框架。

## 最高优先级停止条件

- 如果 minimal handoff 无法在基本不降低 downstream success 的前提下降低接管成本，
  就先修产品核心，不扩 adapter；
- 不得用增加 adapter、策略数量或文档数量代替实际任务质量提升。

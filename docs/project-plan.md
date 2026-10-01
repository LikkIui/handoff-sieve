# HandoffSieve 项目计划（接手修订版）

> 状态：历史接管与工程记录；当前开发优先级以 `iteration-roadmap.md` 为准
> 修订日期：2026-10-01
> 正式名称：HandoffSieve；distribution `handoff-sieve`；import
> `handoff_sieve`。公开仓库为 `LikkIui/handoff-sieve`，GitHub `v0.3.0a1` 已发布，PyPI 暂缓。
>
> **产品版本路线已重新调研并移至 [`iteration-roadmap.md`](iteration-roadmap.md)。**
> 本文件继续记录 0.1 接管、安全基线和既有工作；其中阶段 6/7 的旧描述不再作为
> 未来版本定义。
> 当前定位是 receiver-specific context / handoff optimization；本文后续的安全加固内容
> 仅是已完成的底层能力，不代表当前产品主线或近期待办。

## 最新接管状态（2026-10-01）

v0.1–v0.3 的核心实现、20 项真实接管评测及两个框架适配已完成；公开安装包可从 GitHub
下载。PyPI 因维护者邮箱问题暂停，不是产品开发阻塞。当前新增同一历史面向 coder /
reviewer 的双接收方 demo，已用发布 wheel 在源码目录外验证，README 提供完整上手路径。

`0.3.0a2.dev0` 已加入 OpenAI SDK 实时 contract filter 和实际工具 → 交接流程，修复
运行中新状态未自动纳入、同一消息多个 section 被归入首个标题两个缺口。两个 live coder
条件均通过 6/6；网关 usage 异常如实保留，不宣称本轮账单节省。缺失状态的结构化反馈
和修正示例已补齐，SDK 缺失时阻止交接、补正后完成 6/6。下一步改善必要状态和 preferred
内容的预算占用反馈，帮助调用方调整契约；不扩框架或追加模型试验。
下面保留的是历史工程记录，
其旧版本号和当时的未完成项不代表当前状态；最新优先级见迭代路线。

## 0. 历史执行进度（2026-09-28）

已完成：

- 建立可回退基线提交 `35817f7`；
- 清除嵌套 Git 和指向旧复制目录的虚拟环境，将项目平移到唯一 Git 根目录；
- 将本计划纳入 `docs/`，并把 CI 工作流移到 GitHub 可识别的根目录；
- 完成下列 8 项 P0 加固，并增加相应回归测试；
- 在 Python 3.13 新虚拟环境中安装 core、OpenAI Agents SDK 和 tiktoken 可选依赖；
- 通过 73 项测试，包括真实 `HandoffInputData`、双 Agent 离线 Runner、
  最低/当前 SDK、并发隔离、审计导出和 tool call/output 完整性测试；
- 完成版本化审计合同：关联 ID、时间与耗时、policy 版本、安全配置指纹、
  本地估算/供应商用量分离，以及 callback/JSONL reporter；
- 完成固定离线 benchmark、确定性 Writer 合同、五类 denied-path 审计和
  Failure Zoo V2；基准结果由 JSON 自动生成 README 表格并由 CI 校验；
- 修复评测发现的摘要输出秘密重注入和脱敏后错误去重两个质量缺口；
- 成功构建 sdist 与 wheel，并在第二个隔离环境中从 wheel 安装运行。
- 将候选版本推进为 PEP 440 `0.2.0a1`，以 `_version.py` 作为打包与运行时
  版本的单一来源；
- 增加 changelog、发布清单和已安装制品冒烟脚本；CI 会从空目录验证 wheel，
  并解包 sdist 运行其自带测试与 benchmark。

当前保留事项：

- 已完成命名冲突初筛并选择 HandoffSieve；本地源码、distribution 和 import 已统一，
  远端仓库改名、PyPI 实时复核与名称保留仍待执行；
- P1 首轮阻塞已关闭；SDK tool-pair、不支持模式和双 Agent 离线端到端 handoff
  已通过验收；
- 固定 benchmark 已通过全部验收门槛；正式命名与发布坐标仍待工作包 F 处理；
- 尚未发布、推送或创建远端版本。

## 1. 接手时项目判断（历史记录）

HandoffSieve 当前是一个可运行的 Alpha 原型。核心策略、YAML 配置、审计模型、
OpenAI Agents SDK 适配器雏形、示例和离线测试已经存在，但尚未达到公开发布所需的
安全边界、真实框架验收和质量证明标准。

当前状态应表述为：

> 功能原型完成，V0.1 发布加固进行中。

在安全边界和真实 handoff 验收完成前，不发布稳定版，不扩张为完整 Agent 框架，
也不同时开发多个框架适配器。

## 2. 接手时产品定位（已由当前路线取代）

### 一句话定位

> 一个框架无关、可测试的 Agent handoff 策略门：在上下文跨越 Agent 边界前，
> 执行确定性筛选、脱敏、预算、关键内容保护和审计。

### 核心价值

HandoffSieve 应当回答以下问题：

1. 接收 Agent 最终会看到什么？
2. 哪些内容被删除、修改、保留或拒绝？
3. 敏感信息是否被阻止越过边界？
4. 整个 handoff 是否真的满足总 token 预算？
5. 关键约束、引用、结论和工具消息关系是否仍然完整？
6. 处理后，下游 Agent 是否仍能完成任务？

### 差异化方向

HandoffSieve 不以“策略数量最多”为目标。PII 检测、摘要、上下文裁剪和完整可观测性
已有成熟项目。HandoffSieve 的差异应当是：

- 跨框架使用同一套 handoff policy contract；
- 默认确定性、离线可测；
- 对关键约束和控制消息提供明确的不变量；
- hard budget 针对接收方完整输入，而不是局部分段；
- 提供可重复的 handoff conformance tests 和质量评测；
- 审计不保存敏感原文，并可以导出给现有 tracing/observability 系统。

## 3. 明确不做的范围

近期不开发：

- Agent 创建、运行和路由决策；
- 工作流编排和动态拓扑；
- 会话数据库、任务队列、RBAC、Web 管理后台；
- 自建完整 DLP、NER 或 prompt-injection 模型；
- 自建 tracing UI；
- 跨 Agent 的长期记忆系统；
- 完整 A2A 服务端；
- 未经真实需求验证的大量框架适配器。

专业能力优先通过可选适配器接入，例如 Microsoft Presidio、LLM Guard、OpenTelemetry
或现有 observability 平台。

## 4. 核心设计原则

### 4.1 唯一外发表示

系统必须定义唯一的 canonical egress representation。任何最终可能被接收 Agent、
模型提供商、日志系统或审计系统看到的字段，都必须明确属于以下一种：

- 可外发且必须接受策略处理；
- 内部字段，永不序列化；
- 明确禁止并在入口拒绝。

脱敏、token 计数、Schema、审计和 adapter 必须针对同一外发表示，不能分别维护
不同的字段范围。

### 4.2 信任边界

调用方输入不得直接设置内部保护状态。`protected`、source index、framework control
标记等只能由 pipeline 或受信任 adapter 创建。

调用方提供的 tags、metadata、sender 和 receiver 默认视为不可信数据；它们必须经过
校验、大小限制和清晰的传播规则。

### 4.3 默认安全行为

- 使用路由规则时，未匹配 handoff 默认拒绝或显式告警，不静默放行；
- 关键内容无法放入预算时明确失败；
- 策略失败必须返回可关联的 denied audit report；
- 无法保证兼容的框架模式必须明确报不支持；
- 不宣传绝对防泄漏、绝对准确或无损压缩。

### 4.4 Canonical state 与 receiver view 分离

框架的原始会话状态、checkpoint 或 session history 不应被 HandoffSieve 隐式改写。
HandoffSieve 默认生成只供接收 Agent 使用的 receiver view，并单独返回审计结果。

## 5. 当前已知阻塞

### P0：发布前必须解决（首轮已完成）

1. [x] 脱敏和 token 预算覆盖 canonical envelope 的全部公开字段；模型 extra 默认拒绝。
2. [x] `protected` 和 adapter reconstruction state 改为私有状态，公共入口无法伪造。
3. [x] YAML route 未匹配时默认 `error`，并支持显式 `warn | pass`。
4. [x] OpenAI adapter 合并 history、pre-handoff 和 input items 后统一预算和去重。
5. [x] 使用真实 SDK `HandoffInputData`/`InputItem` 完成离线集成测试。
6. [x] 摘要后端 usage 缺失时使用 pipeline 本地计数，不再记零。
7. [x] Schema normalization 审计 changed/removed field count。
8. [x] handoff report 增加版本、ID、状态和失败码；策略异常携带 denied report。

### P1：Alpha 发布前解决（首轮已完成）

1. [x] Adapter 报告已改为 context-local 状态，并通过共享实例并发隔离测试。
2. [x] Alpha 明确使用同步 pipeline；async summarizer 会携带 denied report 明确拒绝。
3. [x] 自定义 regex 已增加统一错误、数量/大小/扫描上限和逐匹配超时。
4. [x] overlapping rules 默认拒绝，并支持显式 `first | all` 与稳定 rule ID 审计。
5. [x] CI 已覆盖 Python 3.10–3.13、OpenAI 0.22.0/0.22.3、tiktoken、wheel、Ruff 和 mypy。
6. [x] 已补配置、扩展 Policy、adapter 能力矩阵和威胁模型文档。
7. [x] 已重建虚拟环境并移除嵌套 `.git` 与旧路径依赖。

## 6. 执行路线

以下阶段是发布门槛，不按日历日期强行推进。上一阶段验收未通过时，不宣布下一版本
完成。

### 阶段 0：项目接管与仓库恢复

目标：让当前目录成为唯一、可复现、可提交的项目来源。

工作项：

- 确认唯一 Git 根目录，处理外层和内层嵌套仓库；
- 将本计划和必要说明文件放入受版本控制的 `docs/`；
- 重建本地虚拟环境，消除指向旧目录的 editable install；
- 从 wheel 和干净源码两种方式验证安装；
- 记录当前 26 项测试结果并建立首次基线提交；
- 调查 GitHub、PyPI、域名及潜在商标冲突，确定正式名称；
- 在正式名称确定前，不发布包或制作不可复用的品牌资产。

验收标准：

- 新机器或干净临时环境可从仓库安装并运行测试；
- `git status` 能准确表示项目状态；
- 没有嵌套 Git、旧路径依赖或被忽略的关键项目文档；
- 有可回滚的基线提交。

### 阶段 1：安全边界与数据模型加固

目标：保证所有外发内容都经过同一套策略、预算和审计。

工作项：

- 定义 `IngressEnvelope`、内部处理状态和 canonical egress/wire representation；
- 禁止输入设置内部 `protected`、source index 等保留字段；
- 明确 extra fields 策略：默认拒绝、剥离或显式白名单；
- 让 redact、token counter、Schema 和 audit 覆盖全部外发字段；
- 给 sender/receiver 定义安全标识规则，防止审计报告泄露客户标识或邮箱；
- 新增 `on_unmatched: error | warn | pass`，安全预设使用 `error`；
- 为每条规则生成稳定 rule ID，报告记录实际匹配规则；
- 定义 overlapping rules 的顺序、合并和冲突行为；
- 统一安全策略顺序：preserve → redact → deduplicate → select/summarize → budget；
- 对危险顺序给出配置错误或明确警告。

测试要求：

- Envelope、Message、Artifact 的所有外发字段；
- nested dict/list、字段名、超长 metadata、Unicode 和空值；
- 伪造 protected/internal 字段；
- route 拼写错误和新增 Agent；
- overlapping wildcard rules；
- protected-only budget overflow；
- property/fuzz tests 验证“敏感标记不得出现在 egress”。

验收标准：

> 对任意接受的输入，系统能枚举完整 egress，所有 egress 字节都被纳入脱敏、预算和
> 审计；调用方不能伪造内部状态绕过策略。

### 阶段 2：审计、成本与失败语义

目标：让审计结果足以解释一次 handoff 是否允许、修改了什么以及成本如何计算。

工作项：

- [x] 定义稳定、版本化的 `AuditReport` JSON schema；
- [x] 增加 handoff/request ID、时间戳、耗时、状态和失败原因码；
- [x] 记录 policy 名称、版本、rule ID 和安全的配置指纹；
- [x] 分开记录 estimated usage 与 provider-reported usage；
- [x] pipeline 始终自行计算 summarizer input/output，provider usage 作为补充；
- [x] 记录 Schema 规范化导致的 changed/removed field count，但不保存字段值；
- [x] 预算、Schema、配置和摘要失败时返回 denied report；
- [x] 提供 reporter/exporter protocol，支持 JSONL、回调和后续 OpenTelemetry 集成；
- [x] 禁止 exporter 默认接收原始 handoff 内容。

验收标准：

- 每次成功或失败运行都有一个可关联报告；
- 报告可解释每类修改，但无法还原被脱敏的值；
- 成本统计不会把摘要调用错误宣传成免费节省。

### 阶段 3：OpenAI Agents SDK 适配器硬化

目标：完成第一个真正通过验收的框架适配器。

工作项：

- 为 adapter 定义统一 contract：`to_envelope → process → from_envelope`；
- 将 `input_history`、`pre_handoff_items` 和 `new_items/input_items` 合并为一次逻辑
  handoff，在总输入层面执行预算和去重；
- 保存 segment、source occurrence 和控制消息映射，处理后正确还原；
- 保护 handoff、function call、tool output 及 call ID 配对；
- 原样保留 `run_context`，不把本地应用状态暴露给模型；
- 用 per-call result、回调或 context-local 状态替换共享 `last_reports`；
- 明确支持矩阵：client-managed history、nested history、server-managed conversation、
  Realtime、streaming；
- 对不支持的模式给出明确异常和替代用法；
- 测试最低支持 SDK 和当前 SDK，避免无限制依赖未来破坏性版本。

测试要求：

- 使用真实 `HandoffInputData` 和 SDK RunItem 类型；
- 不调用付费模型的离线 adapter integration tests；
- 总预算跨三个 segment 生效；
- 跨 segment 去重；
- tool call/tool output 配对不损坏；
- `new_items` 的 session history 语义保持不变；
- 并发复用同一 adapter 时报告不串扰；
- server-managed 和 Realtime 兼容边界测试。

验收标准：

> 两个由真实 OpenAI Agents SDK 驱动的 Agent 能在离线测试模型或测试工具下完成一次
> handoff，接收方完整输入满足策略和总预算，控制消息关系保持合法。

### 阶段 4：Handoff 质量评测与 Failure Zoo V2

目标：证明压缩和脱敏之后，下游任务仍然成功。

建立固定、可公开、无真实秘密的数据集，至少包含：

- 长上下文与重复搜索结果；
- 多种 API key、邮箱、手机号和自定义秘密；
- 五条必须遵守的约束；
- 可验证的引用和结论；
- 成对工具调用与工具结果；
- 结构化 Artifact；
- route 未匹配、预算不足和 Schema 失败；
- 恶意 protected/metadata/extra fields 输入。

核心指标：

- secret/PII recall 与 false-positive rate；
- constraint、citation、conclusion 保留率；
- downstream task success rate；
- tool-pair integrity；
- 原始输入、摘要成本、接收方输入和净 token 变化；
- pipeline 延迟；
- 相同输入与配置的确定性；
- audit completeness。

最重要 Demo：

```text
Researcher → HandoffSieve → Writer
```

必须同时证明：

- 敏感信息没有进入 Writer 的 receiver view；
- 五条约束全部保留；
- 引用仍可使用；
- 总输入满足预算；
- Writer 最终任务通过；
- 报告准确反映所有修改和成本。

验收标准：

- Demo 是自动断言，不是截图或人工描述；
- 评测可在 CI 中离线重复运行；
- README 中的数字全部来自固定 benchmark 输出。

### 阶段 5：V0.1 Alpha 发布

目标：发布一个范围小、承诺准确、可以被外部开发者复现的 Alpha。

发布工作：

- [x] 确定正式候选 HandoffSieve、distribution `handoff-sieve` 和 import
  `handoff_sieve`，完成本地统一；
- [ ] 将远端仓库改为 `handoff-sieve`，复核并保留 PyPI 坐标；
- [x] 补充当前项目 URL、维护者、安全报告渠道和 PEP 440 版本策略；正式改名时
  再一次性更新 URL；
- [x] 提供 `py.typed`、lint、类型检查和 build 配置；
- [x] CI 覆盖 Python 3.10–3.13、最低/当前 OpenAI SDK、sdist/wheel 安装；
- [x] 从 wheel 运行 quickstart、Failure Zoo 和 adapter smoke test，并从解包的
  sdist 运行完整测试和 benchmark；
- [x] 编写配置参考、自定义 Policy、adapter 能力矩阵、威胁模型、迁移说明和
  `docs/release-checklist.md`；
- [ ] 在正式名称确定后增加受保护的 Trusted Publishing release workflow；
- [ ] 发布 GitHub prerelease 和 PyPI `0.2.0a1`；
- [ ] 收集真实用户的框架、策略和失败案例需求。

V0.1 Alpha 发布门槛：

- 所有 P0/P1 阻塞关闭；
- clean wheel 测试通过；
- 至少一个真实框架 adapter 通过 conformance suite；
- 所有成功和失败路径都有审计结果；
- benchmark 同时报告安全、质量、token 和延迟；
- 文档明确能力边界和不支持模式；
- 没有“绝对防泄漏”或“无损压缩”等无法证明的宣传。

### 阶段 6：跨框架验证

目标：证明 core contract 可以跨框架复用，而不是仅为 OpenAI SDK 定制。

优先实现 LangGraph/LangChain adapter：

- 转换 `BaseMessage[] ↔ HandoffSieve Envelope`；
- 返回 receiver-view state patch 和 `AuditReport`；
- 不接管 `Command.goto`、active agent 或工作流路由；
- 保留 AI tool call 与相同 call ID 的 ToolMessage；
- 默认不覆盖 canonical/checkpoint state；
- 复用和 OpenAI adapter 相同的 conformance suite。

验收标准：

- 同一 fixture 和 policy 配置在 OpenAI 与 LangGraph adapter 上满足相同不变量；
- 框架差异只存在于转换层，core policies 不包含框架判断。

### 阶段 7：A2A 1.0 边界

目标：把 HandoffSieve 应用于跨进程或跨组织的 Agent 通信边界。

在实现前先扩展 core 对以下对象的明确支持：

- Message Part：text、data、file、URL；
- Artifact Part 和媒体类型；
- task/context/message/artifact ID；
- extensions 和 reference IDs；
- streaming chunk 聚合与跨 chunk 敏感模式。

首个实现优先选择 outbound client interceptor 或 server handler decorator，不构建完整
A2A 服务端。协议 ID、role、task state、媒体类型和 append 语义默认不可被策略删除。

验收标准：

- 对完整逻辑 Message/Artifact 执行策略；
- 不破坏 A2A 任务状态和引用关系；
- streaming 在无法安全聚合时明确拒绝或降级为只审计；
- 后续再评估可协商的 HandoffSieve A2A extension。

### AutoGen 适配器

AutoGen adapter 不作为近期发布阻塞。只有在出现真实使用方或完成 A2A 前置评估后，
再实现 AgentChat wrapper，并复用统一 adapter contract 和 conformance suite。

## 7. 建议工作包顺序

### 工作包 A：接管基线

- 移动并修订计划；
- 清理仓库和环境结构；
- 确定正式命名流程；
- 建立基线提交和 clean-install CI。

### 工作包 B：Egress Contract

- canonical wire representation；
- 内部状态私有化；
- 全字段 redact/count/audit；
- fail-closed routing；
- P0 对抗测试。

### 工作包 C：Audit Contract

- [x] 版本化报告；
- [x] denied result；
- [x] 成本与 latency；
- [x] reporter/exporter protocol。

### 工作包 D：OpenAI Adapter

- [x] 完整 handoff 合并预算；
- [x] 当前 SDK `HandoffInputData` 集成测试；
- [x] tool-pair integrity；
- [x] 并发安全与能力矩阵；
- [x] 双 Agent + 离线测试模型的完整 handoff 验收。

### 工作包 E：Evaluation

- [x] benchmark fixtures；
- [x] downstream task assertions；
- [x] Failure Zoo V2；
- [x] README 自动生成的实测数据。

### 工作包 F：Alpha Release

- [x] 选择 HandoffSieve，并统一本地 distribution、import 和文档坐标；
- [ ] 改名远端 repository，复核并保留发布坐标；
- [x] `0.2.0a1` 打包元数据、单一版本源、changelog 和自包含 sdist；
- [x] wheel/sdist 干净安装、离线示例、adapter smoke 和 `pip check`；
- [x] 文档、安全说明和可执行发布清单；
- [ ] GitHub/PyPI Trusted Publishing prerelease；
- [ ] 外部反馈。

## 8. 近期决策清单

在工作包 A/B 期间需要确定：

1. [已决策] 正式名称使用 HandoffSieve，PyPI distribution 使用
   `handoff-sieve`，Python import 使用规范下划线形式 `handoff_sieve`；
2. [已决策] 使用 rules 时，`on_unmatched` 默认固定为 `error`；只有显式配置才
   允许 `warn` 或 `pass`；
3. [已决策] Message 和 envelope extra fields 默认拒绝，Alpha 不开放隐式
   allowlist；
4. [已决策] 审计按原样记录 sender/receiver/request ID；调用方必须传入不含邮箱、
   客户名、凭据或消息正文的安全 alias/hash；
5. [已决策] Alpha 只提供 sync pipeline；async summarizer 携带 denied report
   明确拒绝；
6. [已决策] provider-reported token usage 与本地 estimate 使用独立字段；
7. [已决策] 首批 exporter 同时提供 JSONL 和 callback，OpenTelemetry 后续接入；
8. [已决策] OpenAI Agents SDK 支持窗口固定为 `>=0.22,<0.23`，CI 验证
   0.22.0 与 0.22.3；扩展上界前必须先通过 adapter integration suite。

## 9. 成功标准

项目进入下一个阶段，不以文件数量或策略数量判断，而以以下结果判断：

- 一个外部开发者能从干净环境安装并复现 Demo；
- 任意外发字段都不存在绕过策略和预算的隐藏通道；
- 失败默认可见、可审计、可测试；
- 同一 policy contract 可在两个框架中保持相同不变量；
- benchmark 能证明安全收益没有以明显破坏下游任务为代价；
- 用户可以在不采用新的编排框架、数据库或管理后台的情况下接入 HandoffSieve。

## 10. 调研依据

- OpenAI Agents SDK Handoffs：<https://openai.github.io/openai-agents-python/handoffs/>
- OpenAI Agents SDK Tracing：<https://openai.github.io/openai-agents-python/tracing/>
- LangChain PII Middleware：<https://reference.langchain.com/python/langchain/agents/middleware/pii>
- LangChain Agent Middleware：<https://www.langchain.com/blog/how-middleware-lets-you-customize-your-agent-harness>
- Microsoft Presidio：<https://microsoft.github.io/presidio/analyzer/>
- LLM Guard：<https://protectai.github.io/llm-guard/get_started/quickstart/>
- A2A 1.0 Specification：<https://a2a-protocol.org/latest/specification/>
- Multiagent Handoff：<https://github.com/aznikline/multiagent-handoff>
- HandoffRail：<https://github.com/MelaBuilt-AI/HandoffRail>
- OpenGrove Handoff：<https://github.com/open-grove/handoff>


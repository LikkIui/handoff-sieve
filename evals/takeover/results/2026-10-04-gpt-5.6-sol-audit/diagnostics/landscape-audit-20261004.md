# HandoffSieve 外部项目与下一版方向勘察

勘察日期：2026-10-04（Asia/Shanghai）。本文件是工作记录，不修改产品路线或发布版本。

基线：本地 `0.3.0a3`，提交 `3a8d608a47c58c31c093f27d1aac485840c3dba3`；
OpenAI Agents SDK `0.22.3`、LangGraph `1.2.12`。读取了 README、
`docs/iteration-roadmap.md`、ReceiverContract / compiler / state preparation 和本地 SDK 源码。
只浏览官方文档与项目作者仓库；本子任务没有任何模型 API 调用。

## 结论

HandoffSieve 仍有合理空间，但下一版需要把「receiver-specific」从 section 级推进到条目级。
框架已经提供 history filter、session trimming、summarization 与 compaction。继续增加摘要方式或
支持更多框架，辨识度有限。它应该解决的是：同一任务中的编码员与审查员怎样拿到不同的、
足够完成接管的信息，并说明丢掉了什么。

以下「可借鉴/空缺」均是结合已读取内容与本项目源码作出的判断，不是对外部项目所有功能的
穷尽证明，也不是已经完成的实现。

## 六个代表性原始来源

| 来源 | 已核对的现实能力 | 对 HandoffSieve 的启发与边界 |
|---|---|---|
| [OpenAI Agents：Orchestration and handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration) | handoff 是控制权交接，官方建议每个 specialist 做窄任务；支持结构化 metadata 和过滤 history。文档没有标注发布日期，本次读取的是 2026-10-04 页面。另核对本地 `agents/handoffs/__init__.py`：`input_filter` 可改变 receiver 输入，`input_items` 可与持久 session history 分开。 | filter hook 是集成接口，不是本项目的新卖点。区别应是可复用的 receiver contract、足够性反馈与条目选择。SDK 的 server-managed conversation 不支持 handoff input filters；现有适配边界继续明确，不为它另建会话平台。 |
| [OpenAI Cookbook：Short-Term Memory Management with Sessions](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory) | 页面发布日期 2025-09-09，本次核对 2026-10-04。示例按完整用户 turn 保留最近 N 轮（含 tool calls/results），以及将旧历史生成为摘要。文档比较了硬截断的上下文丢失与摘要的额外调用/状态失真。 | 应把「最近 N 轮 / 原生过滤」当便宜而有用的比较对象，而不只和 full history / 摘要比较。项目不需要重做 session 数据库；按当前接管角色保护旧决定和失败经验比按年龄裁剪更具辨识度。 |
| [LangChain/LangGraph：Handoffs](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs) | 2026-10-04 核对。subgraph handoff 可控制消息流；需要保持 `AIMessage` tool call 与 `ToolMessage` 配对；官方指出完整内部历史会制造无关上下文，不同角色可能需要不同视图。页面未标出发布日期。 | 当前配对能力应继续保留。下一版重点是同一 State 的不同接收者视图；不增加 routing framework。官方例子部分假定没有并行 tool call，不应据此放松现有配对回归。 |
| [LangChain：Context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering) | 2026-10-04 核对。明确区分持久 State/Store 和单次模型输入的 transient context；可以在不改保存状态的前提下改变模型所见消息、工具、提示。页面未标出发布日期。 | HandoffPacket 是视图，不应变成完整历史唯一存储。原始状态留在应用端，下一接收者只得到视图；连续交接若需要已删除的信息，应显式从原始状态重新选取，不能声称 packet 能恢复它。 |
| [Microsoft LLMLingua](https://github.com/microsoft/LLMLingua) | 2026-10-04 核对 README 与 [compressor 源码](https://github.com/microsoft/LLMLingua/blob/main/llmlingua/prompt_compressor.py)。LLMLingua-2 用经蒸馏的 encoder 做 token classification；支持 rate/target token、force tokens、结构化区段不压缩等控制；需要模型加载与 Transformers。论文标为 ACL 2024 Findings，仓库不能据 README 新闻日期推定最后更新。 | 可借鉴「把不可损失的结构/标识与可压缩正文分开」，但不宜默认引入本地 ML 模型、GPU 或 embeddings。它解决文字压缩；receiver 的需求、决定/TODO 生命周期与接管成功仍是本项目要解决的问题。仓库的最大压缩率不能转用于本项目宣传。 |
| [RTK（rtk-ai/rtk）](https://github.com/rtk-ai/rtk) | 2026-10-04 核对 README。针对测试、构建、diff 等命令输出做格式相关的过滤，成功项合并、失败保留；提供失败/截断时恢复原始输出的存储方式。它明确区分命令输出压缩与总账单节省，并说明 token 数为 bytes/4 估算。页面未标出发布日期。 | 优先做 1–2 种大 tool result 的明确视图，比通用摘要更容易保持低算力且验证。可借鉴「失败优先 + 可回看原始结果」，不照搬整个 CLI/hook 生态，不用它的宣称压缩率替代本项目在线结果。 |

补充边界：[OpenAI Compaction 官方文档](https://developers.openai.com/api/docs/guides/compaction)
于 2026-10-04 核对，其 compaction item 是不面向人阅读的 opaque state；standalone compact
返回的窗口应按 canonical window 原样传递。HandoffSieve 可检查的 JSON packet 与这类
provider-specific 会话续接是不同目的；不应尝试自行切割 opaque compaction item，也不需要
追随它建设整套会话系统。

## 当前代码中与外部能力比较后最明显的缺口

1. `ReceiverContract.goal` 目前是输出目标，编译器不会根据它理解内容相关性。
   `required=("decisions",)` 表示完整带上 decisions section，不等于自动找到和目标有关的决定。
   README 的「receiver-specific」当前主要来自不同 section 的需求。
2. `prepare_sender_state(task_id=...)` 已解决不同任务之间的显式隔离、state_key 更新与去重，
   但同一 task 内多个模块或接收角色仍会共享该 section 的所有条目。
3. preferred 条目按 contract 的 section 顺序、输入历史顺序依次尝试。它不会主动把新的、
   与接管文件相关的证据排在旧的无关证据前面；当前机制可预测，但可能浪费紧预算。
4. 大 artifact/tool result 是完整内容的原子项。放入 required 可能溢出，放入 preferred 可能整项
   被省略。现有基础摘要 policy 不等于这些 required 条目可以安全地、无损地变短。
5. README 的 20-task checkpoint 是单次 trial，当前 compact renderer 的 17.2% 是离线估算。
   三 Agent relay 目前用本地 fixture models。不能用这三类不同证据宣称在线连续交接已经证明。

## 建议优先级与最小交付

### P0：把当前紧预算与连续交接的真实失败找出来（当前勘察轮）

在线实验只服务于回答上述缺口：同一任务含旧决定/已完成 TODO/大工具日志/不相关模块时，
coder → reviewer 是否仍能完成，哪些内容被遗漏，是否增加重试。使用相同模型、起点与 host-side
验收，不把 retry 偷算成新的成功首轮。不需要新建大 benchmark 平台或要求统计显著性。

补充一个便宜的「recent-turn/raw filtered」比较对象即可明确区分本项目和框架内置过滤的价值。
真实 task 的原始日志与失败都保留。若 HandoffSieve 掉成功率，先修核心，不发布更多 adapter。

### P1：v0.4 候选主特性——同一 task 内的 receiver 条目选择

先做显式选择：例如按 `Message.tags`、已存在的 `metadata.state_key` 和 `Artifact.name` 选择。
需要哪些标识由应用/contract 明确给出，不默认调用模型猜目标，不加入 vector DB。
可以先用一个小的 preselection helper 验证使用感，再决定是否把小型 selector 放进 contract；
不要一开始设计查询语言。全局约束必须显式保留，required 缺项继续报错，不静默变为 preferred。

一个有辨识度的 demo：同一 sender/task 有 auth、cache、release 三个模块；coder 只取 auth
实现决定和文件，reviewer 取 auth 证据/失败尝试/修改结果，双方共享必须遵守的兼容性约束。
验收包括 packet 差异、关键条目保留、预算、独立接管成功和源状态不变。

理由：这直接加强产品一句话，比多一种摘要 backend 或多一个框架更有价值。

### P2：大工具结果的“小视图 + 原始内容可回看”

选一个最常见、结构明确的结果（例如机器可读测试报告）和一种普通长日志：
保留 command、exit code、失败断言、文件路径、成功/失败数量；只对明确识别的成功噪声做合并。
未知格式按原结果传递，或明确要求调用方提供摘要。对接现有 artifacts 即可，不新增远程存储服务。
原始数据由调用方保存，receiver packet 中可选本地引用；默认不建立任意文件读取或自动 fetch。

这属于显式有损视图，需标出“原文未全部包含”；不能叫 compact renderer 那样的无损重渲染。
若原始 tool call/result 作为结构仍需配对，摘要应替换内容而不移除配对身份。

理由：现实上下文的大头常是工具输出，RTK 证明格式专用的低算力处理方向可用，但本项目仍应
围绕交接时的一次选取，避免扩成命令代理。

### P3：根据实测优化大历史的编译热路径

源码 preferred 循环对每个候选构造并计数整个 packet；选择项增长时存在重复序列化/计数。
本文件仅确认代码形态，具体耗时与复杂度由主任务 profiling 给出，不预先虚构 p95 数字。
最小目标是复用单条序列化/计数或每次编译的临时 cache，避免修改公开输出。
不全局缓存可变 envelope，也不把 tokenizer 的边界效应假设为严格可加。
任何加速必须保留同样的选择顺序、exact hard-budget 终检、完整 required 状态和自定义 counter 语义。

理由：低算力是项目价值之一，但应解决实际大输入瓶颈，不引入线程池、服务或复杂缓存系统。

## 建议版本节奏（提案，尚未修改 roadmap）

- 若 profiling 找到独立加速/正确性问题，可收为小型 `0.3.0a4` 修订，报告输入规模和前后耗时。
- 下一有用户价值的能力版可称 `v0.4`：主特性为 receiver 条目选择，配一个真实连续接管 demo。
  大 tool view 仅在真实结果显示其为主要瓶颈时放入同版，否则后置。
- 当前 core 在真实连续交接中可靠后，才考虑 `0.3`/`0.4` 稳定版；不为了版本号先写 `1.x → 2.x`。

## 无需追随

不扩 OPA/Cedar/A2A 企业安全平台、不扩框架列表；不重建 session/checkpointer/长期记忆平台；
不默认引入 LLMLingua/embeddings/GPU；不支持 RTK 的整个 CLI 命令生态；不做通用 compaction
服务。不把更多测试数、文档数、adapter 数和压缩百分比当作下一版的主要成果。

所有方向的停止条件继续是：如果减少上下文不能在基本保留接管成功的前提下减少总接管成本，
就修核心选择与足够性，而不是增加周边功能。

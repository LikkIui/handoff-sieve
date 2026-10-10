# HandoffSieve 0.3.0a3 优化勘察（2026-10-04）

勘察与 API 验证完成于 2026-10-05（Asia/Shanghai）。

范围：已发布 `0.3.0a3`，源码提交 `3a8d608a47c58c31c093f27d1aac485840c3dba3`。
本轮检查性能、状态选择、两个适配器、真实接管效果及相关开源方案。
核心源码和发布版本保持原样；本文是有证据的下一轮建议。

## 当前结论

项目已经有可用的 receiver-specific packet 编译和交接基础。最值得推进的是
**从选择信息类别，进一步选择接收任务需要的具体条目**，并把已有状态准备能力
自然接入历史和两个框架入口。大型 preferred 选择与 artifact 去重也存在明确性能瓶颈。

这轮仍围绕 `ReceiverContract`、`HandoffPacket` 和 Minimal Sufficient Handoff。
不需要企业安全协议、更多适配器、向量数据库或默认增加一次摘要模型调用。

## 本地性能：有两个明确的二次复杂度路径

环境为 Windows、Python 3.13.2、Pydantic 2.13.5、tiktoken 0.14.0。
构造数据不在计时内，每项预热一次后测量三次，保留原始样本和输出等价检查。
以下是工作站测量，不是 CI 阈值或模型 API 耗时。

| 路径与规模 | 当前实测 | 具体原因 | 下一步 |
|---|---:|---|---|
| 1000 条 preferred，4000-token 预算，保留 63 项 | 中位 3.45 秒；三次 1.19 / 3.45 / 4.27 秒 | 每个候选都重新构造或深拷贝整包并计数 | 每次编译复用工作结构，单项构造后追加/回退；保留终检 |
| 1000 条 preferred 全保留 | 中位 52.43 秒 | 两轮选择均随保留项增长重复整包工作 | 优化两轮，不以删掉必需信息换速度 |
| 相同 1001 项输出，evidence 全部 required | 中位 0.452 秒 | 避开 preferred 逐项尝试 | 用作定位对照，不能把改为 required 当修复 |
| 连续交接合并 5000 个不同 artifact | 中位 24.96 秒 | 每项与已有整列表做模型相等比较 | 按名称分桶，同名桶内保留原相等、覆盖和冲突语义 |
| 5000 条历史 normalization | 中位 1.11 秒 | 多次公共状态复制 | 低优先级；仅删除有隔离证明的冗余复制 |

1000 preferred 全保留时，`count_text` 被调用 2007 次，累计扫描约 256 MB，
最终接收 JSON 仅约 254 KB。profile 显示整包模型重建和深拷贝占主要时间；
只换 tokenizer 或加一个计数缓存不足以修复这个问题。

局部工作原型验证了默认 Approx 第一轮和 artifact 名称分桶的加速可能性，
尚未实现完整 compiler 优化，不能把局部加速比当作产品端到端收益。
`TiktokenCounter` 继承 `ApproxTokenCounter`，快路径不能靠 `isinstance` 判断；
BPE 和自定义计数器需要精确计数路径。政策处理后的第二轮预算检查仍然必要。

独立复核还发现：浅复制 normalizer metadata 会让合法的非 JSON 可变对象与输入共享。
该候选暂不建议上线，调用方输入隔离优先于这部分小幅加速。

证据：[性能报告](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/performance-audit-20261004.md)、
[原始样本](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/performance-audit-20261004-results.json)、
[4000-token 预算样本](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/performance-tight-budget-20261004-results.json)。

## 正确性和产品能力

| 优先级 | 发现 | 定性与建议 |
|---|---|---|
| P1 | tiktoken 遇到正文里的 `<\|endoftext\|>` 直接报错 | 明确 bug；将字面文本按普通字符计数，增加正文与 packet 回归 |
| P1 | LangGraph 合法 text-block 内容无法识别 Decision/TODO | 兼容缺口；提取已知文本块，明确非文本块处理 |
| P1 | `required` 只验证 section 有项，空字符串决策也可通过 | 提供有意义内容诊断；避免禁止合法空工具输出 |
| P1 | 同 section 的早期无关项先吃预算，末尾关键证据被省略 | 当前 FIFO 规则的限制；增加预算前显式条目选择 |
| P1 | 普通标题需先 normalize 再 prepare，才能关闭已完成 TODO | 统一可选入口：分类 → scope/状态更新/去重 → contract → 预算 |
| P1 | 框架映射未传递应用的 task_id/state_key | 提供明确应用状态/映射钩子，避免整包转发 provider 内部 metadata |
| P2 | 大 artifact/tool result 作为整体占满 required 预算 | 做明确的小视图，保留失败、退出状态、路径和可读取的原文引用 |

`goal` 目前不会驱动语义理解。`required=("decisions",)` 保证 decisions 类别，
不保证找到了当前任务需要的决定；后续 `SelectPolicy` 也无法剔除已被保护的选中项。
应在 required 预算前选择，不能取消 required 保护来实现裁剪。

首跳未保留的信息不能从 packet 恢复，这符合当前文档的边界。应用应保存完整 sender
状态，再为新接收者生成视图；一个 packet 不应成为唯一历史存储。

证据：[核心质量审查](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/core-quality-audit-20261004.md)、
[十个边界复现](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/core_quality_repro_20261004.json)。

## 真实 API 检查

使用用户授权的兼容网关及请求模型 `gpt-5.6-sol`。该名称由网关接受，
无法独立确认网关实际使用的模型或其定价。凭据只用于认证，不存入结果。

20-task 对照沿用公开任务、相同 starter、相同公共任务指令和隐藏行为验收，
每任务每条件一轮，无自动网络重试；另有三组合成条目选择压力任务，各两轮。
超时和错误保留在分母，报告区分本地估算、回传 provider usage 和请求耗时。
这些 sender state 是预先构造、分类过的较短状态；该组主要检验已整理状态的接管，
不代表未经标注的长历史、复杂真实仓库或任意团队工作流的成功率。

所有 20-task 输入已由匿名下载的公开源码包重新生成，核对 63 个源码/任务文件文本，
并保存 60 条准备/接收提示词哈希。未发送内部文档或真实工作区状态。
合成压力输入仅由脚本字面量构造；这些任务用于检验机制，不是现实用户成功率。

### 20 个公开接管任务：少传信息已成立，成功率等价还未成立

| 条件 | 成功 / 全部任务 | 模型超时 | 返回后行为验收失败 | Handoff tokens 合计（本地估算） | 回传 input tokens | 回传 total tokens | 请求数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full History | 17/20 | 2 | 1 | 15025 | 16338 | 34541 | 20 |
| Naive Summary | 16/20 | 2 | 2 | 9792 | 32807 | 63032 | 40 |
| HandoffSieve | 16/20 | 2 | 2 | 6773 | 10547 | 29644 | 20 |

每个 Naive Summary 任务包含一次摘要准备和一次接管调用；回传 usage 两者都计入。
Handoff tokens 仅指交接上下文，不含共同任务提示、工具定义或输出。
HandoffSieve 相对原 Full History 少传 **54.92%**，相对 Naive Summary 少传 **30.83%**。
这轮 HandoffSieve 比完整历史少成功一个任务，不能写成“成功率完全不掉”。

三组各有两次 180 秒模型超时，全部保留在分母；没有自动重试或挑选成功重跑。
仅描述正常返回结果，三组分别为 17/18、16/18、16/18；这不是替代主结果的成功率。
三条件都正常返回的相同 15 个任务，结果为 14/15、13/15、13/15，仍存在一项差异。
单轮小样本与网关超时无法支持稳定等价、优于完整历史或真实账单节省的结论。

回传 usage 只累计已收到的数据；超时请求的实际计费未知，不能按零费用解释。
这轮摘要准备的 20 次调用均完成；目前失败也不能继续归咎于旧摘要提示词问题。
正常返回的 receiver 请求中位耗时依次为 78.40 / 66.92 / 84.67 秒；Summary 还另需
摘要准备。本轮网关表现没有证明 Sieve 的端到端响应更快，本地编译提速和模型响应耗时
必须分开看。

失败归因复核发现两点，不能仅看分数就修改产品：

- `pe07_file_manifest`：Summary 和 Sieve 都缺少验收要求的 `size`，但三个实际输入均未
  明确清单行字段和 SHA-256 契约。完整历史本轮猜中了，不能据此认定另外两组丢失了原有事实。
- `pe02_cli_color`：存在真实的参数解析错误。Full/Summary 错误处理重复的显式 `auto`
  后跟 `never`；Sieve 接受了非法的 `--color sometimes`。此外，验收还拒绝裸 `--color`，
  原公共指令只笼统要求拒绝 malformed，未明确必须带值，存在可修正的题目歧义。

原始成绩保持不变。下一次正式评测应先补齐公共任务契约，再让三条件使用同一版本的题目，
不能改验收去迁就模型答案，也不能把协议修订后的结果覆盖到本轮 20-task 上。

### 两个歧义任务的补充对照：单独记录，不覆盖原成绩

对 PE-02 仅补充 `--color MODE` 必须带合法值；对 PE-07 仅补充 path / size / sha256
字段含义。新增要求放在各条件相同的公共任务指令中，摘要准备也能看到。没有提供测试
样例、隐藏答案、参考实现或参数跟踪算法。Full/Sieve 的原交接上下文字节完全不变，
core、sender state、ReceiverContract 和评分器保持原版。

| 补充条件 | PE-02 | PE-07 | 成功 / 任务 | 请求数（含摘要准备） | 可用回传 total tokens |
|---|---|---|---:|---:|---:|
| Full History | 验收未通过 | 通过 | 1/2 | 2 | 4312 |
| Naive Summary | 通过 | 通过 | 2/2 | 4 | 6893 |
| HandoffSieve | 通过 | 通过 | 2/2 | 2 | 2609 |

8 次请求全部正常返回，零自动重试，合计 13814 回传 tokens。原先两组缺少 `size` 的
问题在明确字段后均未再出现。这与公共契约不足的归因一致，但补充提示与重新采样同时
发生，单轮结果不能证明全部差异的唯一原因，也不能用 2/2 宣称总体质量优于完整历史。

该补充仅帮助区分题目要求、模型实现错误和状态裁剪；原主表继续保留 17/20、16/20、16/20。
证据：[补充协议与哈希](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/clarified-tasks-live-20261005/protocol.json)、
[补充结果](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/clarified-tasks-live-20261005/aggregate.json)。

### 同一任务内选择关键条目：下一功能版的直接依据

三个合成任务各重复两轮；每条状态有相同 task_id，现有 task scope 无法区分它们。
故意让早期无关 evidence 占满预算，把关键规则放在后面。原型仅在预算前依据显式
receiver 标签选择具体条目，保留共享约束；没有增加模型、向量检索或人工修改答案。

| 条件 | 成功 / 请求 | 模型超时 | 返回后验收失败 | 平均 handoff tokens（本地估算） | 可用回传 total tokens |
|---|---:|---:|---:|---:|---:|
| Full History | 6/6 | 0 | 0 | 432.3 | 4741 |
| 当前 HandoffSieve | 0/6 | 0 | 6 | 313.0 | 3957 |
| 显式接收条目选择原型 | 5/6 | 1 | 0 | 280.0 | 3287 |

当前包严格遵守预算，但丢失了必要规则；更短的原型包正常返回的 5 次全部通过行为验收。
第六次超时保留为失败。原型尚未进入公开 API，依赖应用提供准确标签，不能自动理解 goal。
**这是刻意构造的信息丢失机制实验，不是现实用户成功率，也不是发布后的普遍提升幅度。**
它说明“先选择正确条目，再做预算”比继续扩 adapter 更接近项目的核心价值。

### 连续接力：真实 coder → reviewer 已走通

使用公开示例的固定 Researcher 状态，coder 和 reviewer 调用真实模型，执行现有 SDK
和两次 ReceiverContract filter。Researcher 本身是离线 fixture；不是三个 Agent 都由
模型独立研究生成，也不是三条件成功率评测。

- 4 次真实 Responses 请求，85.55 秒，零网络重试、零代码修正重试。
- coder 实际写入生成的函数并运行原有行为验收，**5/5** 通过。
- reviewer 实际调用独立工具，在新目录验证接口和所有布尔组合，**9/9** 通过；宿主复核同样通过。
- 两个接收者的首次模型输入均精确等于对应 canonical packet；独立复核还逐项核对了实际
  HTTP 请求 1 和 3 的 `input`，分别只含对应包，且没有 `previous_response_id` 或
  `conversation` 带入额外历史。四次请求体与所记录的模型输入全部一致。
- 首跳本地估算从 2038 tokens 到 237；第二跳从 564 到 542。第二跳已经主要是有用的新工作，不应强求每一跳都有很高压缩率。
- 回传 input/output/total tokens 分别为 **2955 / 319 / 3274**，四次 HTTP 均 200，回传模型名均为请求别名；这不构成网关底层模型身份的独立证明。

接力的 `workflow_success=true` 同时要求真实文件检查、两次交接、reviewer 实际用工具、
输入边界正确和最终 verdict 正确；不是只采信模型自报“通过”。

### 调用与证据总账

本轮共 **111 次真实 API 请求**：20-task 对照 80 次、连通性探测 1 次、定向压力 18 次、
连续接力 4 次、公共需求澄清对照 8 次。收到 104 次响应，7 次模型超时；自动网络重试为 0。
可用回传 total tokens 合计 **156341**，包含 51-token 探测，不包含超时请求的未知 usage。
离线准备、mock transport 和性能原型均未计入真实调用数。

原始记录：[20-task 汇总](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/live20/aggregate.json)、
[20-task 请求记录](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/live20/calls.jsonl)、
[条目选择压力汇总](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/selection-stress/aggregate.json)、
[真实连续接力](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/relay-live-20261005.json)。
失败归因、逐组耗时和总账：[独立结果复核](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/final-results-independent-review.md)。
2026-10-10 更新：本轮公开任务的原始结果和诊断记录已归档到上述 Git 跟踪目录；inventory.json 保存逐文件 SHA-256。模型输入/输出及原成绩没有重写。诊断脚本仍留在本地 work/。

现有完整测试本轮重新运行：**349 passed**。这些测试没有覆盖本轮发现的全部边界，
测试数量不能替代接管质量。

## 格式收益与选择收益分开看

对同一公开 20-task，离线 Approx handoff 总数：

| 表示 | 总 tokens |
|---|---:|
| 原 Full History 格式 | 15025 |
| 相同公共状态的紧凑 Full History | 13213 |
| 当前 HandoffPacket | 6773 |

20/20 紧凑完整状态往返恢复相同。纯完整历史格式优化减少 12.06%；
packet 相对这个紧凑完整历史再减少 48.74%。后者仍混合内容选择、metadata 省略
和结构开销变化，不能全部称为语义收益，也不能推算模型成功率或账单。
当前公开 Full History 的定义准确；后续可用一个紧凑完整历史控制，增强归因清晰度。

证据：[格式公平性结果](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/format-fairness-results.json)。

## 下一版本建议

### 一个短小的修订，解决明确错误和耗时

可收为 `0.3.0a4`：修正特殊标记计数和 LangGraph 文本块，优化 preferred 两轮工作结构
及 artifact 合并。完成条件为同样输入得到同样 packet/选择顺序/预算结果，并保持
自定义计数器、政策变换、输入隔离、同名版本和失败行为。用小型规模检查验收，
不增加一套 benchmark 平台，也不因只增加测试数而发布。
评测题目同步补齐已发现的公共契约歧义，先复核两个受影响任务即可，不要求重建大规模数据集。

### v0.4 主特性：Receiver-specific Item Selection

同一个 task 中，coder 和 reviewer 应能明确选择不同的具体状态，而非只选择不同 section。
首版优先以已有消息 tags 做精确接收方选择，明确配置共享约束；附件按名称选择仅在 demo
需要时加入。state_key 继续服务于已有状态更新，不一次新增三套筛选语法。
不引入查询语言、向量库或隐式收费模型。保留 section 级默认兼容行为；指定必需条目缺失时
提供诊断，不能用其他同类项替代。启用条目选择时，required 指所选视图中的完整类别。

已有 `prepare_sender_state(task_id=...)` 和 `SelectPolicy(tags=...)` 不应重新包装为新突破。
新增价值是把接收方选择直接表达在合同中，在预算和 required 保护前执行，并自然接入两个
现有框架。标签仍由应用明确提供；这不是自动理解自然语言目标。

统一历史与适配器入口的准备顺序，使应用无须自行拼接多步才能处理已完成 TODO 和过期状态。
用同一 sender 含 auth/cache/release 三个模块的一个完整接力 demo 验收：
coder 取 auth 实施状态，reviewer 取对应证据、失败尝试和新工作；包明显不同，
同预算下关键事实仍在，独立任务验收通过，原始 sender 状态保持完整。

大工具结果小视图仅在实际接力显示其为主要问题时进入同版；原文引用必须能被 receiver
读取。减少文本但让接收者无法完成任务的“节省”不算成功。

停止条件继续是：context 缩减若降低接管质量，就先修核心；不以 adapter、文档或策略数量
替代任务质量提升。PyPI 的暂停与本轮产品能力优化无关，不成为发布前置条件。

有界实施与验收复核：[独立优先级审查](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/final-priorities-independent-review.md)。

## 相关项目给出的启发

- [OpenAI handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration)
  已支持过滤历史，[官方 Session 示例](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory)
  已展示裁剪/摘要。本项目应加强接收任务的具体状态选择，而非重复会话摘要。
- [LangGraph handoffs](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs)
  与 [context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering)
  支持控制接收者上下文；完整应用状态与单次输入视图应分开。
- [LLMLingua](https://github.com/microsoft/LLMLingua) 提供模型驱动文字压缩，
  可借鉴保护结构的思路，本项目的低算力默认路径不需要加载压缩模型。
- [RTK](https://github.com/rtk-ai/rtk) 的格式相关工具输出过滤值得参考，
  先借鉴失败优先、原文可回看，不扩成命令代理生态。

这些下一步是结合本项目实测作出的判断；竞品的宣称压缩率没有计入本项目证据。
完整原始来源核对见 [相关项目调研](../evals/takeover/results/2026-10-04-gpt-5.6-sol-audit/diagnostics/landscape-audit-20261004.md)。

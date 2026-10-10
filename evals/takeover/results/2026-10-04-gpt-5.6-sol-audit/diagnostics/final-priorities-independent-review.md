# 下一版优先级独立复核（2026-10-05）

复核对象：`0.3.0a3` / `3a8d608a47c58c31c093f27d1aac485840c3dba3`。
仅检查源码、现有路线和本次离线勘察；没有调用 API、读取凭据、修改 core 或发布。

## 结论

“一个短修订 + 一个接收方条目选择版本”符合用户的小工具定位，但必须区分修复、已有
能力的接入和真正的新价值。修订版不必等待一个复杂状态查询系统。下一主版本只需要证明：
**同一任务、同一类信息中，coder 和 reviewer 得到不同的相关条目；共享约束仍在，同样
预算内能够完成接管。** 无需新增框架、隐式模型摘要、向量检索、协议或大型评测设施。

本轮报告提出的三种匹配键（tags / state_key / artifact name）不应自动成为一次发布的
三套选择语法。最低范围可以先支持消息的精确 receiver tags 和附件的精确名称；state_key
继续用于现有状态更新，确有使用需求时再增加作为选择键。API 最终名称尚未设计，不把
此文中的概念变成新的冻结接口。

## 已有能力，不能重新算作版本突破

| 能力 | 当前位置 | 正确定位 |
|---|---|---|
| 按 task_id 选择当前任务及无 task_id 的共享消息/附件 | `src/handoff_sieve/state.py:15`、`:47`、`:70` | 已有；auth 与 marketing 使用不同 task_id 的 demo 不足以证明 v0.4 新价值 |
| 同任务、同 section、同 state_key 的后写覆盖 | `src/handoff_sieve/state.py:55` | 已有；不是新的接收方条目选择 |
| Completed 关闭旧 TODO，后续 TODO 可重新打开 | `src/handoff_sieve/state.py:60` | 已有；普通 history 的归一化顺序和入口接入是改善易用性 |
| 按角色 / kind / tags 选择消息 | `src/handoff_sieve/policies/select.py:11`、`:31` | 已有策略；不同字段用 AND，同字段 tags 用交集，不需要重新发明筛选算法 |
| contract 只声明 goal / required / preferred / budget | `src/handoff_sieve/compiler.py:141` | 当前 goal 不做语义理解；section 选择不能保证具体事实相关 |

调用方今天可以自行预筛选 envelope，再调用 compiler，因此新特性应明确描述为
**接收合同内显式表达、预算前执行、缺失有诊断、两个现有入口可直接使用的条目选择**，
不能宣称第一次拥有 tags 筛选能力。压力原型的手工 tag 筛选证明机制可行，并不证明新的
公共 API 已经实现或普通用户任务的成功率。

## 短修订的最小实施范围

### 1. 字面特殊 token 计数：最先修

位置：`src/handoff_sieve/tokens.py:84`–`:85`。计数普通文档和源码时，`<|endoftext|>`
这样的字面字符串不应触发 tiktoken 的禁止特殊 token 异常。按普通字符编码即可，
不用改模型、预算定义或添加 API。

验收只需覆盖正文、JSON 内容和 canonical packet 的字面标记；空文本仍为 0，正常
文本计数保持原结果。不要把允许文本计数解释为可以执行或特殊解释该标记。

### 2. LangGraph 标准文本块：小兼容修复

位置：`src/handoff_sieve/adapters/langgraph.py:39`–`:42`、`:163`–`:172`。目前字符串
Decision/TODO 能被归一化，等价的标准 text blocks 保持 list 后不能被识别。

最低范围是可识别的纯文本块按顺序拼接，保留标题行界；等价 string / text-block 输入
应编译出同样分类、内容和预算结果。未知块或 text/image 混合不能静默丢非文本内容：
保留当前保守行为或给明确诊断。工具调用及结果配对、前一包识别行为必须保留。

### 3. preferred 两轮重建：主要性能修复

位置：`src/handoff_sieve/compiler.py:528`–`:552`、`:778`–`:785`；公共条目构建在
`:670`–`:724`。本地证据支持同时优化两个循环：只是优化 tokenizer、只优化第一轮
或把 preferred 改为 required 都不能完整解决瓶颈。

可以先避免每个候选重复重建/深拷贝整个已选包，然后给默认 Approx 计数建立精确的
UTF-8 字节增量路径。`TiktokenCounter` 继承 Approx（`tokens.py:59`），因此不能用
`isinstance(ApproxTokenCounter)` 分流；BPE 和自定义计数器保留精确整包计数回退。
第二轮必须按处理后的 packet section 保留身份（`compiler.py:701`–`:704`），不能
重新依据已被变换的公开 kind 归类，也不能删除处理后 required 超预算的明确失败。

有界验收：

- 100 / 1000 个候选，两种预算（4000 和全保留），原/新 canonical 输出与 BudgetReport
  相同；输出条目、FIFO 顺序、required 完整性和源状态独立性相同。
- “前一项太大、后一项能装下”的输入仍跳过大项、继续考虑小项。
- Unicode / 引号转义 / 不同 section / 附件有确定性预算边界样例；不需要几百 gold packets。
- 一个政策使内容变长，另一个改变公开 kind，验证第二轮 hard budget 与 section 不变量。
- tiktoken 与一个非可加的自定义 counter 继续走精确路径。
- 记录同机前后完整编译样本；不把局部原型 33708→98 ms 宣称为产品端到端加速。

按工作量安排，特殊计数及文本块可先形成修复，compiler 优化随后合并。不要让清理全部
normalizer 复制或工具结果格式成为这次修订的前置条件。

### 4. artifact 名称分桶：独立的小优化

位置：`src/handoff_sieve/adapters/_packet.py:58`–`:66`。使用名称桶，再在同名桶内做
原模型相等比较，能改善常见多文件路径。原输出顺序、当前附件替换同名继承附件、同名
不同当前版本同时保留、独立公共复制全部保持。

验收包含 current/inherited 同名覆盖、同名冲突、精确重复，以及内容值 `1` / `1.0` /
`True` 的原相等语义；不能改用普通 JSON 字符串 hash。记录 100 / 1000 / 5000 不同
名称的样本即可。同名大量版本仍有桶内最坏情况，这不是通用常数时间保证。

## v0.4 的最小核心范围

### 预算前的接收方条目选择

当前位置：contract missing/required 验证从 `compiler.py:457` 开始，required 全量追加
从 `:495` 开始。条目选择必须发生在这之前。现有 SelectPolicy 的 protected 绕过在
`policies/select.py:50`，解除 required 保护来让它生效会破坏当前合同，不是修复方案。

建议只有一个显式选择机制，允许精确指定接收标签与附件名称、显式指定共享标签。
空选择配置保持现有 section/FIFO 默认行为。选择前后还可以使用现有 task_id 及状态
准备，但这些功能不再增加一组重复的合同字段。首版不支持自然语言查询、优先级打分、
通用谓词 DSL、正则路由或自动 infer goal 的语义。

必须明确以下语义：

- section 级 required 在新选择配置下指**所选接收方视图中的该类完整内容**；未配置
  条目选择时仍指原 section 的全部内容。文档不能不提这个作用域变化。
- `global` / 共享约束由显式配置保留，不能按“没标签”猜共享，亦不能误删共享决定。
- 指定的必需条目不存在或被 scope 筛掉时明确失败。仅用“section 有一项”不足以证明
  指定条目存在；诊断区分没选到、原始没有与预算不够，不能隐式用其他同类项替代。
- section 标签和接收标签分开使用；例如 `evidence` 表示类，`receiver:coder` 表示
  接收用途。包含互相冲突的 section 标签仍保留当前错误行为。
- 任意接收者的新视图从应用保存的完整 sender state 生成；不能要求上一跳已省略的
  信息凭空从 packet 恢复。无需增加 session 数据库或多跳追踪协议。

### 统一准备顺序：接入现有能力

`compile_history` 当前在 `normalization.py:296` 归一化后直接调用 compiler；两个
框架编译入口为 `adapters/openai_contract.py:147` 和 `adapters/langgraph.py:249`。
提供一个可选配置，按“映射 → normalize → 现有 prepare → 条目选择 → contract/budget”
执行，默认完全兼容。不要加多个平行的 history / contract API。

LangGraph 在 `langgraph.py:164` 当前重建 metadata，只携带 name。仅允许应用明确映射
task_id/state_key/接收 tags 等业务字段，或一个明确的应用状态钩子；不要整体复制 SDK
run_context / provider additional_kwargs。OpenAI 的 live filter 也应使用同一准备配置，
不能仅在离线 core demo 生效。入参始终不变，诊断的原始位置归属应可解释。

最低验收：普通 TODO 与 Completed 同 state_key 只保留 completed；新 pending 可重新
打开；共享和 task-specific key 不互相覆盖；两个已有 adapter 的已完成工具 pair 仍为
一个语义项；继承包合并新状态后能选择新的接收视图。无需新 adapter 或并行工作流系统。

### 一个真正显示新增价值的 demo

同一个 task_id 中包含 auth / cache / release 的多条 evidence 和 artifacts，标签明确。
所有条件固定相同预算和全局 API 约束：当前 section/FIFO 会先装入无关项而丢关键事实；
coder 视图选择 auth 实施事实；reviewer 视图选择对应证据、失败尝试及新产物。
两个包都可检查且不同，发送方完整状态不丢失。coder 的实际产物通过行为验收，reviewer
独立读取可获得的产物并检验行为。接力中原文没有可读取路径的“引用”不算保留。

验收到一个清晰、可复现、正确的接力和必要回归即可。已完成的合成压力测试可佐证
FIFO 丢关键信息的机制，但不需要扩大到 200 packets / CI / 置信区间。真实调用的超时、
解析失败和任务失败应保留并分开报告；筛选多出的本地工作不应额外调用摘要模型。

## 暂缓项与权衡

- 空 required 内容诊断可以作为小补充；它不是“所有空内容都无效”的通用新规则。尤其
  合法空工具输出不能被全局禁止。先规定具体文本决策/约束的有意义诊断再考虑失败条件。
- normalizer 的浅复制候选已有可变非 JSON metadata 共享反例。本轮不接入；节省约
  0.2 秒不能换取输入隔离失效，也不应偷偷缩小公共模型的 Any 范围。
- 大 artifact / tool 小视图在真实接力证明是主要障碍前暂缓。实现时必须保存成功/失败、
  退出信息和接收方实际能读取的原文，不能以不可读路径制造 token 节省。
- tags / 名称选择零模型算力，代价是发送应用必须提供可靠标签；README 明说它不做
  语义理解。无标签资料保守诊断，不能为漂亮压缩率自动删除可能关键的事实。
- 没有因调用更多 API 就能证明选择充分。接管质量下降时停止扩展、修本体；增加适配器、
  文档或策略数不能代替质量提升。PyPI 的邮箱暂停不影响此核心工作。

## 复核依据

- `docs/optimization-review-2026-10-04.md`
- `docs/iteration-roadmap.md`
- `work/performance-audit-20261004.md`
- `work/core-quality-audit-20261004.md`
- `work/audit-20261004/run_selection_stress.py:329`（私有显式 tag 原型）
- 上表列出的当前源码位置；本复核不改变原始性能记录或真实 API 分数。

## 追加：真实连续接力及最终报告独立复核

复核文件：`work/audit-20261004/relay-live-20261005.json` 和
`work/audit-20261004/run_live_relay.py`；另读完成后的
`docs/optimization-review-2026-10-04.md`。没有新增 API 调用或修改 core。

### 实际 HTTP 输入，而不只是模型层变量

脚本的 `boundary_checks` 字段本身在 `run_live_relay.py:243`–`:247` 比较
CapturedModel 记录的 input 与 canonical packet，不能单凭这些布尔值声称检查了 HTTP。
实际请求体由 `:169`–`:172` 的 httpx request hook 在发送边界读取，响应由
`:174`–`:182` 留存，且 hook 已在 `:185` 实际接入客户端。

本次独立按完整 JSON 对象核对后确认：

- 第 1 个实际 HTTP 请求是 coder 首调用，`body.input` 恰为唯一
  `{"role":"user","content": <coder canonical packet>}`；包 SHA-256 对应 handoff。
- 第 3 个实际 HTTP 请求是 reviewer 首调用，`body.input` 恰为唯一 reviewer canonical
  packet 项；包 SHA-256 对应第二次 handoff。
- 以上两个请求均没有 `previous_response_id` 或 `conversation`，输入中均没有被过滤的
  launch/hosting notes。请求的 instructions / tools 是公开的新 Agent 行为说明，
  不属于原历史夹带。
- 全部 4 个实际 HTTP 请求的 input 与对应 CapturedModel 输入逐项精确相同；各自
  HTTP response_id 与 ModelResponse.response_id 也对应，4 个响应均 HTTP 200。
- 第 2、第 4 请求分别正常携带本 Agent 当前轮的工具调用和真实结果；不能把“每个
  接收者首调用只有 packet”扩大说成后续所有调用永远只有一个 packet。

因此最终报告“两个接收者首次输入精确等于对应包、无原历史混入”有实际序列化层证据，
不是只检查准备变量。可把文字写为“首次实际 HTTP input 也已独立核对”；自动
`workflow_success` 字段的输入检查范围仍是模型层，本次独立复核补齐 HTTP 证据。

### 文件、验收和调用数字

| HTTP 请求 | 接收方 | 回传 input | 回传 output | 回传 total |
|---|---|---:|---:|---:|
| 1 | coder 首调用 | 538 | 151 | 689 |
| 2 | coder 读写入结果并交接 | 758 | 97 | 855 |
| 3 | reviewer 调独立验收工具 | 734 | 36 | 770 |
| 4 | reviewer 读取验收并给 verdict | 925 | 35 | 960 |
| 合计 | 4 次真实请求、4 次响应 | 2955 | 319 | 3274 |

4 个请求、模型记录、响应记录数量一致，provider_calls=4；时间差为 85.550022 秒。
SDK 和模型重试均配置为 0（`:186`–`:187`、`:224`–`:226`），实际没有重复写入。
仅使用回传 usage，不能据此确定第三方网关底层模型身份或价格。

工具记录中只有一次 `write_and_check_session_policy`：脚本 `:131`–`:133` 真实写文件并
运行公开的验收，结果 passed=total=5、returncode=0、failures=[]。所以“零代码修正
重试”准确；四次请求是正常工具循环与交接，不应被称为四次尝试修代码。

reviewer 仅一次 `independently_review_session_policy` 调用，`:118`–`:124` 从实际文件
读取、复制进新 UUID 目录后调用独立 probe；结果为 keyword-only API + 八种布尔组合
全部通过（9/9，returncode=0）。最终宿主又独立复制检查同一实际文件（`:233`），同样
9/9。最终 approve 与宿主判断相同。因此不是模型自报成功，也不是直接接受 coder 的
5/5 为 reviewer 结果。

Researcher 明确使用 `example.OfflineResearcher()`（`:219`）；只有 coder 和 reviewer
使用实时 OpenAIProvider 模型。报告已明确此边界，不能宣传为三个模型独立研究接力。

### 最终报告表述

本次复核范围内未发现最终报告夸大真实 relay：它披露固定 Researcher、非三条件成功率
评测、网关身份/定价边界、第二跳仅少量缩减，以及 coder 和 reviewer 的实际验收。
其 4 请求 / 85.55 秒 / 2955+319=3274 数字全部与原始记录一致。

同样，报告明确 20-task 本轮 Sieve 为 16/20、Full 为 17/20，不宣称成功率等价；压力
实验明确是刻意构造的机制测试、原型非公开 API。局部性能原型未被当作完整产品加速。
下一版仍是建议而非已实现成果，且没有拓展平台或适配器。上述限定应保留在最终答复中。

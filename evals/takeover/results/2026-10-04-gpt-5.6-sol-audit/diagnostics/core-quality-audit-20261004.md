# HandoffSieve 0.3.0a3 核心质量审查（2026-10-04）

范围：只读审查 core、normalizer、显式状态准备、OpenAI/LangGraph 两个 adapter、连续交接与已有真实评测。没有修改核心、版本或 README，没有调用模型 API。

可重复证据：`work/core_quality_repro_20261004.py` 与同名 `.json`。运行 `.venv\Scripts\python.exe work\core_quality_repro_20261004.py`。这是构造的离线边界实验，不能计入模型成功率。

## 最重要的结论

当前产品已经能编译、交接并在严格预算内发送结构化包；最值得下一版解决的是“同一类别里，哪些事实真正属于接收任务”，以及把已有状态准备能力接入普通历史和框架入口。继续多加 adapter 或安全协议不会解决这些问题。

当前保证是“合同要求的 section 全量保留”，不是“合同目标所需事实已齐全”。这一差别在已有人工预分类的短评测中不明显，在自然对话、多任务混合、长工具输出和连续接管中会成为主要瓶颈。

## 1. 可确认的 bug：tiktoken 遇到普通文本里的特殊标记直接失败

- 位置：`src/handoff_sieve/tokens.py:84`。
- 触发：`TiktokenCounter().count_text("Document literal marker <|endoftext|> in code.")`。
- 实际：`ValueError: Encountered text corresponding to disallowed special token '<|endoftext|>'`。这个值只是待计数的文档/代码字面文本，编译使用此 counter 时会在计数阶段失败。
- 预期：按普通字符计数；它不应被当成控制 token，更不应拒绝整次交接。
- 小范围修复：调用 `encoding.encode(text, disallowed_special=())`，增加含特殊标记的正文/JSON/packet 回归检查。属于可以进入下一补丁版的可靠性 bug。

## 2. Required 目前验证类别非空，不能验证任务关键事实

- 位置：`compiler.py:129`、`:641`、`:727`；normalizer 故意只读明确标签。
- 触发 A：goal 是 auth rotation，历史包含 `Decision: Make the marketing page blue.` 与普通句子 `For auth we accepted httpOnly cookies and one-time refresh rotation.`，required 只有 decisions。
- 实际：合同通过，只发送 marketing 决策；auth 关键事实留在 unclassified index 1 并被丢弃。
- 触发 B：`Message(kind="decisions", content="")` 也满足 required，发出一个空决策 item。
- 定性：A 符合现有明确文档的类别匹配规则，是产品能力缺口；不要声称语义提取已经完成。B 是浅层 required 校验缺口，可以优先对 required section 的纯空占位提供诊断或拒绝，避免全局禁止合法空工具结果。
- 下一版建议：保持低算力，支持明确 task scope / required state keys / 显式 item 优先级。先解决可标注状态的精准选择，不急于添加一个隐藏收费的语义 LLM。

## 3. Preferred 的 FIFO 会让早期无关证据挤掉末尾关键证据

- 位置：`compiler.py:528`、`:778`。
- 触发：required 保留 API constraint；preferred=evidence；先放 marketing invoice，再放 auth expiry evidence，budget 87（恰好容纳前者）。
- 实际：保留 invoice，auth expiry evidence 被省略；budget report 报 evidence omitted=1，却不知道哪条对任务重要。
- 定性：现有算法的设计限制，不是违反 documented ordering 的 bug。
- 下一版建议：按显式 task_id / state_key 做预算前选择，或允许调用方给 item priority；保留现有 FIFO 为默认兼容行为。不要凭自然语言猜测优先级。
- 真实 API 实验适合此题：相同任务、相同隐藏行为验收，分别发送 full history / 当前 packet / 显式 scope 或 priority 后 packet，观察关键边界的成功和实际 prompt usage。不要只比较字符串长度。

## 4. 已有 helper 没有自然地接上 normalize 和 adapter

- 位置：`state.py:15`、`:49`；`normalization.py:279`；OpenAI `openai_contract.py:55`、`:147`；LangGraph `langgraph.py:39`、`:249`。
- 混合任务复现：auth 决策和一条长 marketing 决策均 kind=decisions。全量 required 为 1094 estimated tokens，74 budget 硬失败；显式 `prepare_sender_state(..., task_id="auth")` 后恰好 74 tokens 并通过。
- 顺序复现：两条默认 kind 的 `TODO: Implement auth` 与 `Completed: Auth implemented` 使用相同 state_key。`prepare_sender_state` 再 `compile_history` 仍留下已完成 TODO；先 normalize，再 prepare，才能关闭 TODO。
- README 已明确 state_key 更新仅用于“already classified messages”，所以这不是文档承诺违约。问题在于普通历史用户需自己发现这条组合路径。
- 框架衔接复现：LangGraph `HumanMessage.additional_kwargs` 中给出 task_id/state_key，映射后 Message.metadata 为 `{}`。OpenAI文本映射同样只创建 role/content；两个编译入口只有 normalizer/pipeline，没有预算前 state preparation 参数。
- 下一版建议：提供一个明确、可选的统一入口执行 `normalize → task scope / state update / exact dedup → budget → packet`。映射 application metadata 应使用白名单/回调，不应把 provider 内部 metadata 整包传给 receiver。既有 normalizer Protocol 可以承载一部分组合，缺失框架 metadata 则需要 mapper hook 或显式独立 application state。

## 5. LangGraph 合法文本块与字符串的行为不同

- 位置：`langgraph.py:39`、`_messages_to_state()` 对 content 的传递；normalizer 仅解析 str/dict 形状。
- 触发：`AIMessage(content=[{"type":"text","text":"Decision: Use SQLite.\nTODO: Implement auth."}])`。
- 实际：required decisions/pending_work 两节均报缺失；文本块 list 整项 unclassified。把同样正文放进 content 字符串可以解析。
- 定性：兼容性缺口；并非需要新增 adapter。
- 下一小版：只提取可识别的纯文本块，保留边界和顺序；对非文本块明确报 unsupported 或要求 mapper，避免默默 stringify 图片/音频对象。覆盖字符串与标准文本块等价、混合块、空块和完整 packet JSON 继承。

## 6. Select / Dedup policy 不能当接收任务的 item selector

- 位置：`compiler.py:562`；`policies/select.py` 与 `policies/deduplicate.py` 均保留 protected。
- 实际：所有先被合同选中的 item 都被 protected。实验中 `SelectPolicy(tags={"auth"})` 没有剔除无 auth tag 的 marketing evidence，ExactDedupPolicy 也无法去掉已保护重复项。
- 定性：这是为了避免 required 静默丢失的正确现有行为，不能简单删除保护来“修复”。但用户不能期待后面的 pipeline 解决同 section 的无关内容/重复预算浪费。
- 下一版：选择、状态折叠和精确去重应在 required 预算之前发生，并可解释保留/省略原因；cleanup 继续保留 required 安全边界。

## 7. Artifact 全量内容与未来接力状态需要清晰使用边界

- Artifact 复现：一份 `auth.py` 的 3000 行 `pass` 加 required artifact，预算 500；actual required 4572 tokens，明确 BudgetExceededError。当前 behavior 正确，但全量大文件会吞噬节省价值。
- 小范围产品机会：在接收方确实能访问同一 workspace/tool 时，让应用明确提供路径、相关片段、变更摘要与读取方式。不得静默截断 required 文件，也不能只传 receiver 无法读取的路径来虚称节省。
- 连续交接复现：研究员→coder 的合同只保留 constraints，evidence 在首跳未请求而丢弃；coder→reviewer 新合同 required=evidence 时无法从前 packet 恢复并报 ContractError。
- 定性：不可逆选择是 receiver-specific view 的自然边界，现有文档对此准确。三 Agent demo 的每个合同显式保留未来要用的状态，不能当成任意变化合同均成功。
- 下一版：先完善真实接力例子和完整 sender-state 的 application 管理模式，明确必要的 carry-forward state；不需要可信 lineage、跨组织协议或新平台。

## 8. 现有真实评测的支持范围

- 20 任务保留 exact input/output、provider usage、grader checks；公共 task prefix、公共 starter 和隐藏行为检查相同。full / summary / sieve 都用同一请求模型。summary preparation 成本单列，没有手写一个占优势的 summary。timeout 留在分母、评分修订有审计字段。这些是好的基础。
- 18/20 vs 18/20 与 45.6% handoff / 25.0% provider token reduction 可以准确描述为该 checkpoint 的观察值；不是普遍成功率或计费保证。
- 这些 sender state 大多是人为给定 kind 的短任务，每个重要 section 通常只有一个 item。`taskpack.py:781`、`:826` 展示了固定分类和固定 required 模板。它主要证明“已整理状态的编译选择有价值”，没有检验自然对话分类、同 section 多任务干扰、历史 TODO 更新、大工具结果或真实研究员生成的状态。
- 每任务一次 trial；这既不证明所有模型与 gateway 一样，也不证明连续三 Agent 的真实成功。继续小规模定向实验足够，不应把下一版拖成 200 gold packets 论文工程。
- rr03 Naive Summary preparation 输出的是最终错误 verdict，receiver 重复该 verdict；原摘要 prompt 的输出指令干扰已经如实披露，新 prompt 已隔离引用数据。旧 17/20 含这个旧 prompt 行为，不能说是精简摘要方法的稳定弱点。
- rr03 HandoffSieve 也误判了同一有效候选；full/packet 都包含主要声明，当前材料不能归因于明确漏掉某条事实。不要据此修改 grader 或 prompt 迎合失败答案。
- SDK 单任务 gateway input usage 3867 vs 13960 异常仍未解释，serializer 离线 byte 减少不能解释历史收费数据。新真实实验需保存每次 exact request body/response usage，禁止把未知实际 usage 当零费用。
- 老 checkpoint 的 packet re-render 8177→6773 是离线格式收益，不能补写到旧 provider usage 或 task success 上。

## 建议的小版本顺序

1. 下一预发布/补丁：修复 literal special-token 计数、LangGraph text blocks、required 空占位诊断；保留核心 API 兼容，不做新框架。
2. 下一功能版：统一预算前状态准备，给 ReceiverContract 增加明确 receiver/task/item 匹配和优先级的最小能力；用“关键证据在末尾、混合任务、已完成 TODO”三组有行为验收的 demo 证明收益。
3. 有真实使用反馈再做 artifact references / 大 tool result 的显式选片与证据定位。停止条件仍是：不能以增加 adapter、文档或策略数量替代 downstream task quality 的提升。

以上不是新实现 todo 的擅自扩容；是供主任务收敛下一版重点与真实 API 实验选题的只读审查建议。

## 补充：性能候选独立语义复核

复核对象：`work/performance_candidates_20261004.py`；独立小实验：`work/performance_semantics_verify_20261004.py` 和 `.json`。没有修改产品代码、没有跑付费 API，也没有重复大型计时。

### 第一轮 preferred 的 UTF-8 增量候选

- 32 组不同预算、多 section、Unicode、排序后的 tags、嵌套 metadata、Artifact 同名冲突的固定随机小实验，候选 canonical packet JSON 与完整默认 `compile_handoff()` 的最终输出一致；source 未改。
- 一个巨大早期 evidence 被跳过后，后面的 small evidence 仍保留。required decision 的全部内容保留；候选输出的嵌套字段修改不影响 source。
- 候选只证明默认 `ApproxTokenCounter` 第一轮选择的 byte/4 结果，未覆盖完整 compiler 两轮处理、pipeline 报告与错误诊断。局部 33708→98 ms 的测量不能写成全 compiler 同倍率提升。
- 集成快路径必须使用严格的 counter 能力判断。`TiktokenCounter` 继承 Approx，`isinstance(counter, ApproxTokenCounter)` 不够。独立 `ByteCounter(ApproxTokenCounter)` 用整 UTF-8 字节数作为 token，候选保留一条 evidence 后实际 521 tokens，budget=300；当前完整 compiler 会排除它。必须回退按实际完整 canonical 文本计数。
- BPE 非可加的最小例子：tiktoken `hello` 为 1 token；`hel` 与 `lo` 分别计算再相加为 2。不能用逐片段 token 相加替代全包编码。
- 后处理必须再次预算。独立 `ExpandEvidence` policy 放大一条 evidence：第一轮候选包含它，当前 compiler 第二轮正确排除，`preferred_omitted_after_pipeline.evidence=1`。required 的保护、缺失检查、第二轮硬预算和最终完整文本计数都应保留。
- 建议把优化装入现有选择循环，而不是以候选函数替换整个 compiler。其他 counters 即使慢，也保持原精确终检/行为；默认 Approx 可以借助 canonical item byte 长度获得等价选择。使用公共字段复制不应携带调用者提供的 private protected/internal 状态。

### Artifact name buckets

- 独立三个重点 fixture 通过：同名 `{n:1}` 与 `{n:1.0}` 相等、`{n:True}` 与 `{n:1}` 相等、current 覆盖 inherited 同名并保留 current 不同内容冲突、精确重复移除。
- 输出顺序与原合并逻辑相同，输出嵌套内容修改不影响 inherited/current。
- 按 name 分桶后仍调用原 Pydantic equality，不要改成 JSON 字符串 hash，否则 `1` 与 `1.0` 等现有 equality 语义会改变。
- 不同 name 常见场景可大幅减少比较；同一个 name 有大量不同版本时仍是平方级。不要为了提速猜测哪一版应该获胜。

### Normalizer 最后 shallow copy

- 普通 JSON 可序列化的嵌套 metadata、artifact.content、message.content 独立性通过。
- 找到一个公开 Any 边界反例：`HandoffEnvelope(metadata={"box": MutableAny()})`，该类含可变 `values=[1]`。当前 normalize 的输出修改不影响输入（仍 `[1]`），候选把最后 `source.model_copy(deep=True)` 改为 shallow 后，修改输出会令输入变成 `[1,3]`。
- 这属于 standalone normalizer 接受的 `dict[str,Any]` 情况；非 JSON 任意对象不能进入 JSON packet，但不能因为 compiler 更窄就静默缩窄公开 normalizer 的独立副本承诺。
- 安全收敛方案：只避免最后原 messages 的重复 deep copy，其他剩余 metadata/artifacts 仍保留独立复制；或先明确整体公共 API 仅支持 JSON 状态再评估变更。这个收益比平方级 preferred 与 artifact merge 小，建议后置。

## 补充：真实连续接力检查准备（尚未由本 agent 请求 provider）

- 脚本：`work/audit-20261004/run_live_relay.py`。默认 `--prepare-only`；只有 root 显式使用 `--live` 才会产生真实请求。凭据仅取进程 OPENAI_API_KEY / OPENAI_BASE_URL，不记录 headers。
- 只导入匿名下载的公开 0.3.0a3 源码；发布 archive SHA-256 固定核对，并逐字确认 relay example 与 acceptance 文件。初始状态、API、决策和失败尝试来自该公开 example。没有读取用户/internal state，没有 workspace scan。
- Researcher 沿用公开 OfflineResearcher；live coder/reviewer 使用真实 Responses provider 和请求模型 gpt-5.6-sol，两次现有 OpenAIReceiverContractFilter。
- 最多 10 SDK turns、每模型 4096 output tokens / 180 秒、总流程 900 秒；HTTP 和 SDK 自动 retries 均 0，tracing disabled。coder 最多两次简短源文件写入，不使用隐藏验收反馈救任务。
- 工具实际写文件并运行公开 5 checks；reviewer 的独立工具在新 workspace 执行公开 9 checks。child evaluator 使用最小 Windows runtime environment，不继承 provider credentials。
- canonical packets、第一次 receiver model input、实际 HTTP request body、response IDs、完整 raw usage 与工具/host 结果都单列保存。没有记录认证 headers。异常保留已经发生的请求，不把未知 usage 当零计费。
- 模型 verdict 与 host checks 分开。host_task_success 以实际 9 checks 为准；workflow_success 还要求两次 handoff、live reviewer 真实调用独立工具、receiver packet 精确边界和 verdict 正确。
- 最终 prepare-only 已通过：2 handoffs，coder 5/5，host reviewer 9/9，workflow_success=true，0 网络/API调用。
- 本地 MockTransport smoke 已验证真实 SDK HTTP serializer 路径：4 个模拟 Responses 请求、2 个 handoff、coder/reviewer 工具实际执行、两次第一次 receiver model input 严格等于唯一 canonical packet。记录明确标为 mocked_transport_smoke/fake_metadata，真实 provider calls=0，不可计入真实评测。
- 本 agent 没有执行 --live。真实请求与结果判断由 root 接续；这不是三条件大 benchmark，也不能从 offline/mock 成功推导真实模型成功率。

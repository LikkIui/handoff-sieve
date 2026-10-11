# 源码参考与本次核心改进

本次检查固定提交中的实现，并对两个轻量压缩器直接执行原始代码。比较对象的定位不同，
不能把压缩输出较短解释成接管成功率更高，也不能用我们自己的仿写函数代表对方。

| 项目与固定源码 | 实际实现及值得借鉴的部分 | 对 HandoffSieve 的影响 |
|---|---|---|
| [dabit3/agent-handoff：compress.ts](https://github.com/dabit3/agent-handoff/blob/bc6ccb5db4c22fcffbbd4743d644fd0e11ed1541/src/compress.ts) | `compressRelevance` 分开分配摘要和保留消息的预算；相关性结合时间、角色、focus 匹配及长度。这里的摘要由本地规则生成，不是调用大模型的强摘要。 | 让接管说明与原文证据分工，避免整段原文承担所有说明工作。 |
| [agent-handoff-protocol：HybridCompressor](https://github.com/reaatech/agent-handoff-protocol/blob/4edb996f80412f2fc1108e4bb98be76fc50f8aba/packages/compression/src/hybrid-compressor.ts) | 分别提取摘要、带来源 ID 的事实、实体、意图和待办；`generateSummary` 实际使用首尾内容，不是语义模型。 | 保留来源引用，但使用 receiver goal / needs 来组织说明；引用不被当作语义证明。 |
| [Microsoft LLMLingua：PromptCompressor](https://github.com/microsoft/LLMLingua/blob/5a4c78ae18ab17a98cf997e8259354e546081d64/llmlingua/prompt_compressor.py) | `compress_prompt` 区分上下文、句子及 token 级选择；`control_context_budget` 支持强制保留上下文和不能压缩的片段。需要其模型运行环境。 | 必要原文保持完整，普通说明允许综合；不对代码逐 token 删除，不把新的本地压缩模型加入低算力核心依赖。 |
| [mini-swe-agent：DefaultAgent](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py) | `step` 查询模型再执行动作，执行输出形成下一轮 observation；配套配置要求复现、修改、复测，并记录费用和停止原因。 | 后续评测应接入真实执行反馈。当前便携 source-only 对照尚未整合这个执行器，不能宣称已做到。 |

## 直接运行的对照

`agent-handoff` 和 `agent-handoff-protocol` 使用同一批 16 个已完成研究的 SWE-bench Verified
开发状态。原始 TypeScript 只经固定版 TypeScript 5.9.3 转译；源码 SHA-256 在执行前验证，
没有修改算法。所有输出附完整原始 goal，按 HandoffSieve 的同一个内置估算器重新计数，
而不是混用各项目的内部 tokenCount。

| 原始实现 | 平均完整接收上下文估算 tokens | 完整上下文 ≤ 4,000 | 准备模型调用 |
|---|---:|---:|---:|
| agent-handoff，relevance | 2,937.375 | 13/16 | 0 |
| agent-handoff-protocol，hybrid | 915.0625 | 16/16 | 0 |

这些是输出和大小诊断，**未运行这两个压缩器的下游接管，不构成质量排名**。
`agent-handoff` 的 focus 来自 goal 中长度至少五个字符的英文词，未逐任务调参。
`agent-handoff-protocol` 除 `maxTokens` 外使用默认选项。传入工具消息保留 tool 角色，
没有假装它们是用户/助手消息来适配规则。预算扣除 goal 和空包装后传入，返回值随后完整
序列化，未额外剪裁帮助任何基线。代码审查还发现其 recent-message 分支的内部计数与
返回字段不是同一内容；此次采用默认 preserveRecentMessages=0，没有使用该分支。

[全部返回值、源码固定版本与逐任务大小](../evals/public_swe/results/2026-10-11-reference-compressors/summary.json)
和同目录 `actual-results.json` 保留了可核查证据。LLMLingua 和 mini-swe-agent 此次为源码
机制参考，没有运行它们的完整模型/执行环境，不声称胜过它们。

## 实际落地

新增 [混合交接路径](hybrid-handoff.md)：一次准备调用生成分类接管说明，同时选择必要
原文行范围，由宿主程序复制代码。接管包明确区分观察、建议与待验证假设。继续使用现有
`ReceiverContract`、`HandoffPacket`、预算校验与 SDK 交付边界；原有确定性和抽取路径保留。

第一版让模型逐字抄写 excerpt，实际请求暴露了转义/换行错误。该开发诊断已停止并保留：
11 个请求、8 个完成、7 个包被拒绝、1 个有效；另 3 个在停止时中断，用量未知，没有任何
接管试验。修正版改为来源编号与原文行坐标，不对错误文字做模糊修复。

后续受限响应结构进一步将分类、来源 ID 和需求编号限定在当前 Contract 允许的集合。
这是防止无效响应的产品修正，不等于模型能正确理解需求。8 个固定开发任务的三组全新
接管单独记录；不得与旧 20 题、修正重测或正式 200 题混算。

判断标准仍是强 receiver-aware summary 对照下的接管成功与总成本。如果混合结构不能
改善这些指标，应调整或简化核心，而不是通过更多 adapter 或弱基线制造优势。

## 本轮官方验收结论

[8 题独立对照](../evals/public_swe/results/2026-10-11-hybrid-development-v2-grading/README.md)
为完整历史 3/8、强摘要 4/8、混合交接 3/8，全部控制有效。一次交接响应校验失败属于
产品失败；后续单项修正接管通过，不改写原始结果。同一 7 项实际交付上下文的任务中，
混合结构比强摘要多 31.5% 交接 token，少 13.9% 总 provider token（含准备调用）。
因此这次借鉴已经变成可用代码和成本证据，但还没有变成稳定的成功率优势。

四项任务三组共同失败，Django 13212 三份候选源码均含语法错误，当前接收方没有机会
通过执行发现它们。下一步应借鉴 mini-swe-agent 的行动—反馈循环，让三组共享成熟执行
环境及各自可见测试反馈，再评估交接差异；不是给 HandoffSieve 增加完整 Agent 框架。
官方评分中的 `patch_successfully_applied=false` 也可能表示没有可解析的测试输出，不能
单凭该字段断言 Git 应用补丁失败；依据见
[固定版本评分代码](https://github.com/SWE-bench/SWE-bench/blob/02e7a74ffd0b707aab73d203fe87bdc7c76afc8e/swebench/harness/grading.py)。

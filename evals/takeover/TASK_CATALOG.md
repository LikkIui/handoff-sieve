# v0.3 Takeover Task Catalog

> 状态：20 个任务均已落成 runnable fixture，并已完成首次真实 provider 三条件对照。
> 完整结果、失败和评分修订记录见 `results/2026-10-01-gpt-5.6-sol-20-task/`。
>
> 只有三种输入方案在相同起点、相同接收任务和相同 validator 下完成 real provider run 后，
> 数据才可以计入 v0.3。不得把参考实现通过、单元测试或模拟输出写成模型实测结果。

本目录规划 20 个短小、离线、可客观判定的接管任务：

- researcher → coder：7 个；
- planner → executor：7 个；
- researcher → reviewer：6 个。

每项固定记录五个要素。实现 fixture 时，sender state 中的必要信息应显式归入
`constraints`、`decisions`、`evidence`、`completed_work`、`failed_attempts`、
`pending_work`、`artifacts` 或 `tool_results`；noise 使用其他 `kind`，不得靠模型猜测分类。
所有 validator 应在本地运行，不依赖网络、外部数据库或人工打分。

## Researcher → Coder（7）

### RC-01 Composite cursor pagination

1. **ID / 方向 / 真实任务：** `RC-01`，researcher → coder；在一个小型 Python
   列表分页模块中实现不遗漏记录的复合游标。
2. **Sender noise：** offset pagination 对比文章、数据库厂商宣传、与任务无关的缓存调研，
   以及已经否决的 `created_at` 单字段游标草案。
3. **Required state：** `constraints` 规定公开 API 和游标保持 opaque；`decisions` 规定按
   `(created_at, id)` 升序并使用 exclusive cursor；`evidence` 给出多个记录共享时间戳的
   fixture；`completed_work` 标出已有数据模型和 stub；`pending_work` 要求实现
   encode/decode/page-after；`artifacts` 指向目标文件和公开测试。
4. **Receiver output contract：** 只修改 sandbox 内的分页实现，使
   `page_after(rows, cursor, limit)` 返回下一页和下一游标；坏游标抛出约定的
   `ValueError`，不增加依赖。
5. **Success validator：** 对 50 条含重复时间戳的固定数据分别以 1、7、13 为 page size
   翻页，拼接结果必须与 `(created_at, id)` 稳定排序全集完全相同且无重复；另验证游标
   round-trip、末页和坏游标行为。

### RC-02 Retry-After parsing

1. **ID / 方向 / 真实任务：** `RC-02`，researcher → coder；实现 HTTP
   `Retry-After` 到等待秒数的转换函数。
2. **Sender noise：** 指数退避算法综述、多个供应商限流文档、无关请求日志和已经放弃的
   “只支持整数”实现笔记。
3. **Required state：** `constraints` 固定签名
   `retry_delay(value, now, cap_seconds=60)`；`decisions` 要求接受 delta-seconds 和
   IMF-fixdate，无效值返回 `None`，过去时间归零，结果受 cap 限制；`evidence` 提供冻结
   UTC 时间和边界表；`artifacts` 标出实现文件；`pending_work` 要求补齐解析逻辑。
4. **Receiver output contract：** 完成 stdlib-only 实现，不读取系统时钟，不休眠，也不发起
   HTTP 请求。
5. **Success validator：** 用固定 `now` 对整数、HTTP 日期、零、负差、超 cap、空值和畸形值
   运行表驱动测试，逐项与 reference function 的整数或 `None` 结果比较。

### RC-03 Robust CSV customer import

1. **ID / 方向 / 真实任务：** `RC-03`，researcher → coder；完成一个能处理常见 CSV
   边界的客户导入解析器。
2. **Sender noise：** Excel 样式讨论、导出性能记录、未采用的第三方 dataframe 库比较和
   与客户导入无关的报表需求。
3. **Required state：** `constraints` 规定 stdlib-only、输入为 bytes、必须列为
   `id,name,email`；`decisions` 规定使用 UTF-8 BOM 兼容和标准 CSV quoting/newline 语义；
   `evidence` 提供包含 quoted comma、quoted newline、Unicode 和 BOM 的样本；
   `pending_work` 要求实现 `parse_customers`；`artifacts` 指向 parser stub 和异常类型。
4. **Receiver output contract：** 返回按输入顺序排列的字典列表；缺列或行宽不一致时抛出
   `ImportFormatError`，不得静默丢字段。
5. **Success validator：** 对 BOM、Unicode、quoted comma、multiline record、空文件、缺少
   header 和多/少字段 fixture 做精确结构比较，并验证输入 bytes 未被修改。

### RC-04 Configuration precedence

1. **ID / 方向 / 真实任务：** `RC-04`，researcher → coder；实现四层配置合并。
2. **Sender noise：** 配置框架选型记录、部署平台变量清单、未来热加载讨论和旧版相反优先级
   草案。
3. **Required state：** `decisions` 指定 `CLI > environment > file > defaults`；
   `constraints` 指定只有 `None` 表示未提供，`False`、`0` 和空字符串均是有效覆盖值，未知
   key 忽略，输入 mapping 不得原地修改；`evidence` 给出冲突矩阵；`artifacts` 指向
   `resolve_settings` stub。
4. **Receiver output contract：** 实现纯函数，返回只含 defaults 已声明 key 的新字典，不引入
   全局状态。
5. **Success validator：** 枚举每一层缺失/存在的组合，并专门覆盖 `False`、`0`、`""`；
   与简单 reference merge 比较，同时对四个输入做调用前后深比较。

### RC-05 JSON Merge Patch

1. **ID / 方向 / 真实任务：** `RC-05`，researcher → coder；实现 JSON Merge Patch
   的小型纯函数。
2. **Sender noise：** JSON Patch、diff UI、数据库 partial update 和已经否决的“数组逐项合并”
   方案资料。
3. **Required state：** `decisions` 明确采用 RFC 7396 语义：object 递归合并、`null` 删除
   object member、array 和 scalar 整体替换；`constraints` 要求不修改 target 或 patch；
   `evidence` 给出规范中的代表性输入输出；`artifacts` 指向 `apply_merge_patch` stub。
4. **Receiver output contract：** 实现 `apply_merge_patch(target, patch)`，支持所有 JSON 类型并
   返回独立结果。
5. **Success validator：** 运行嵌套 object、删除、array replace、scalar replace、non-object
   target 和空 patch 用例，并检查输入深拷贝在调用后保持不变。

### RC-06 Canonical HTTP cache key

1. **ID / 方向 / 真实任务：** `RC-06`，researcher → coder；把等价 HTTP request
   规范化为稳定 cache key。
2. **Sender noise：** CDN 厂商功能表、缓存淘汰策略、响应压缩日志和未采用的“直接 hash 原始
   URL”草案。
3. **Required state：** `decisions` 要求 method 大写、scheme/host 小写、移除默认端口和
   fragment、空 path 变 `/`、query pair 按 key/value 排序且保留重复 key 与空值；
   `constraints` 规定使用 stdlib 和 RFC 3986 escaping；`evidence` 给出等价/不等价 URL 对；
   `artifacts` 指向 canonicalizer stub。
4. **Receiver output contract：** 实现 `canonical_cache_key(method, url)` 返回可读 canonical
   string，不访问 DNS 或网络。
5. **Success validator：** 将固定 URL pair 送入实现：语义等价 pair 必须相等，path、重复
   query value 或非默认端口不同的 pair 必须不等；再与独立 reference canonicalizer 比较。

### RC-07 Refresh-token family rotation

1. **ID / 方向 / 真实任务：** `RC-07`，researcher → coder；补完一个小型 session store
   的 refresh-token rotation 状态转换。
2. **Sender noise：** OAuth 历史资料、登录 UI 讨论、JWT 库对比、无关访问日志和已否决的
   access-token 表复用方案。
3. **Required state：** `constraints` 要求保持现有 `SessionStore` API、只保存 token hash；
   `decisions` 要求一次成功 rotate 标记 parent used 并创建同 family child，重复使用 parent
   时撤销整个 family，expired/revoked token 不创建 child；`evidence` 说明现有 rotate 已在
   transaction 内；`artifacts` 指向 store、fake clock 和 tests；`pending_work` 是三条状态路径。
4. **Receiver output contract：** 在现有 store 内实现 rotation/reuse handling，不改公开异常
   类型，不添加远程身份或协议功能。
5. **Success validator：** 用 fake clock 顺序执行首次 rotate、child rotate、parent reuse、
   expired 和 revoked 场景；核对 family 中记录、hash、used/revoked 标记与异常，并验证失败
   路径没有多创建记录。

## Planner → Executor（7）

### PE-01 Streaming CSV endpoint

1. **ID / 方向 / 真实任务：** `PE-01`，planner → executor；按既定计划给 report endpoint
   增加流式 CSV 输出。
2. **Sender noise：** 未来 XLSX/PDF backlog、发布主题会议记录、计费功能规划和无关 ownership
   讨论。
3. **Required state：** `constraints` 要求现有 JSON 响应不变且大结果不能一次性物化；
   `decisions` 指定复用现有 row iterator，通过 `format=csv` 开启；`completed_work` 标出 iterator
   已存在；`pending_work` 列出 serializer、header、Unicode/empty tests；`artifacts` 指向 endpoint
   和测试文件。
4. **Receiver output contract：** 完成 endpoint/serializer patch，CSV 有稳定 header 和 UTF-8
   内容，原 JSON path 行为保持不变。
5. **Success validator：** 校验 empty、Unicode 和普通响应快照；使用只能单次迭代且在提前消费
   时抛错的 sentinel iterator 检查 streaming；运行旧 JSON regression tests。

### PE-02 CLI flag migration

1. **ID / 方向 / 真实任务：** `PE-02`，planner → executor；把 report command 的
   `--output` 平滑迁移为 `--format`。
2. **Sender noise：** 下个大版本的 CLI 重构、shell completion 讨论、发布文案和与该 command
   无关的参数草案。
3. **Required state：** `constraints` 要求默认仍为 `json`；`decisions` 规定新 flag 接受
   `json|csv`，旧 flag 保留为一版 alias 并向 stderr 输出一次固定 deprecation message，同时
   提供两者时 exit 2；`artifacts` 指向 parser 和 CLI snapshots；`pending_work` 列出实现步骤。
4. **Receiver output contract：** 更新 parser、help text 和必要测试，不改变 command 的业务
   输出格式。
5. **Success validator：** 用 subprocess 覆盖无 flag、新 flag、旧 flag、非法值和双 flag；精确
   比较 exit code、stdout/stderr，并验证 help 以 `--format` 为主。

### PE-03 SQLite timezone migration

1. **ID / 方向 / 真实任务：** `PE-03`，planner → executor；执行 jobs 表的 timezone 小型
   schema migration。
2. **Sender noise：** 未来 PostgreSQL 迁移、分库方案、监控 dashboard 规划和其他表的设计会
   记录。
3. **Required state：** `decisions` 指定新增 `timezone TEXT NOT NULL DEFAULT 'UTC'` 并将 schema
   version 升为 3；`constraints` 要求保留既有 row、index 和 status 值；`completed_work` 提供
   migration runner；`artifacts` 包含 v2 seed database 和 migration registry；`pending_work`
   要求增加 migration 与 model default。
4. **Receiver output contract：** 添加一次性 migration 并更新 model/schema version，不引入新
   database backend。
5. **Success validator：** 对临时 v2 SQLite DB 运行 migration，检查旧 row timezone 为 UTC、
   column 的 NOT NULL/default、index 与 status 不变、新 row 获得 default；再次启动 runner 不得
   重复迁移或改数据。

### PE-04 Include runtime template in distributions

1. **ID / 方向 / 真实任务：** `PE-04`，planner → executor；修正 wheel/sdist 遗漏运行时
   template 的打包配置。
2. **Sender noise：** Docker image、PyInstaller、文档站点部署和其他未采用的 packaging backend
   笔记。
3. **Required state：** `constraints` 要求保持当前 build backend 和 import path；`decisions`
   指定 `task_app/templates/default_prompt.txt` 必须同时进入 wheel 与 sdist；`evidence` 是 editable
   install 成功但 wheel 读取失败；`artifacts` 指向 pyproject、template 和读取函数；
   `pending_work` 要求只做必要配置修正。
4. **Receiver output contract：** 更新打包配置，使 `importlib.resources` 在普通 wheel 安装后能
   读取模板；不得把绝对路径写进代码。
5. **Success validator：** 在干净 temp 目录构建 wheel/sdist，检查两个 archive 均含模板，安装
   wheel 后从另一个 cwd 读取并逐字节比较；同时执行 package import smoke test。

### PE-05 Resumable batch checkpoint

1. **ID / 方向 / 真实任务：** `PE-05`，planner → executor；按计划为顺序 batch runner
   增加可恢复 checkpoint。
2. **Sender noise：** 未来并行队列、云存储、进度 UI 规划和无关性能日志。
3. **Required state：** `decisions` 要求 item 成功后才记录 completed id，使用同目录临时文件加
   replace 写 checkpoint，重启时跳过已完成项；`constraints` 要求保持输入顺序、worker 首次
   异常立即向上抛且失败项不落盘；`artifacts` 指向 runner 和 JSON checkpoint schema；
   `pending_work` 给出 load/write/resume 步骤。
4. **Receiver output contract：** 实现 `run_batch(items, checkpoint_path, worker)`，不加入队列或
   并发系统。
5. **Success validator：** fake worker 在 C 首次失败：第一轮调用必须为 A/B/C 且 checkpoint
   只有 A/B；第二轮必须为 C/D；最终 A–D 各成功一次，JSON 可重新读取，并且执行过程中不存在
   partial checkpoint 文件。

### PE-06 Cleanup dry-run mode

1. **ID / 方向 / 真实任务：** `PE-06`，planner → executor；给现有文件 cleanup command
   增加可信的 `--dry-run`。
2. **Sender noise：** 对象存储生命周期、未来 GUI、日志保留政策会议和不相关的 archive feature
   计划。
3. **Required state：** `constraints` 要求 dry-run 与真实执行共享完全相同的 candidate selection，
   不得改文件；`decisions` 指定按相对 POSIX path 排序并逐行输出 would-delete，真实模式保持
   现有删除行为；`artifacts` 指向 cleanup selector 和 CLI；`pending_work` 是参数、输出和测试。
4. **Receiver output contract：** 实现 flag 与共享 selection path，不扩展远程存储支持。
5. **Success validator：** 构造不同 mtime 的 temp tree；dry-run 后 tree 的路径、内容、mtime
   完全不变且 stdout 精确列出过期项；真实运行只删除同一集合，保留临界值与新文件。

### PE-07 Deterministic file manifest

1. **ID / 方向 / 真实任务：** `PE-07`，planner → executor；实现发布目录的确定性文件
   manifest 命令。
2. **Sender noise：** 完整 SBOM 讨论、签名服务方案、云 artifact registry 和发布会议全文。
3. **Required state：** `decisions` 要求只遍历 regular file，排除 `.git/`、输出 manifest 自身和
   `.tmp` 文件，按 POSIX relative path 排序，并记录 byte size 与小写 SHA-256；`constraints`
   要求 canonical JSON 加一个结尾换行；`artifacts` 指向 CLI stub 和 fixture tree；
   `pending_work` 给出 walk/hash/write 步骤。
4. **Receiver output contract：** 完成 `build-manifest ROOT`，输出 `manifest.json`，不加入签名、
   上传或 provenance 系统。
5. **Success validator：** 对含 Unicode 文件名、空文件、nested file 和排除项的 temp tree，与
   独立 reference manifest 做字节级比较；连续运行两次输出必须完全相同。

## Researcher → Reviewer（6）

Reviewer 任务统一要求只输出一个 JSON object：

```json
{"verdict":"approve|request_changes","blocking_issue_ids":["ISSUE_ID"]}
```

不得输出自由文本。`blocking_issue_ids` 必须列出 fixture 中所有被 candidate 违反的 acceptance
rule，且不能加入没有证据支持的 ID。

### RR-01 Review a cursor pagination patch

1. **ID / 方向 / 真实任务：** `RR-01`，researcher → reviewer；审查一个只按
   `created_at` 生成 cursor 的候选 patch。
2. **Sender noise：** 多家数据库分页文章、与 patch 无关的 index 建议、旧 diff 和已经修复的
   offset 性能问题。
3. **Required state：** `constraints` 给出 `CURSOR_TIE_SKIP` 等允许的 acceptance ID；
   `decisions` 是已接受的 `(created_at, id)` exclusive cursor；`evidence` 提供同 timestamp 的
   三行和候选输出 trace；`artifacts` 唯一标明待审 candidate diff；`pending_work` 要求给 merge
   verdict。
4. **Receiver output contract：** 按统一 reviewer JSON schema 返回 verdict 和全部 blocking ID，
   不修改 patch。
5. **Success validator：** 在 candidate 上运行重复 timestamp probe，并将 JSON 与由 probe 生成的
   expected blocker set 比较；该 fixture 的预期是 `request_changes` 与
   `CURSOR_TIE_SKIP`，但这只是 validator oracle，不是模型实测结果。

### RR-02 Review falsy configuration overrides

1. **ID / 方向 / 真实任务：** `RR-02`，researcher → reviewer；审查使用 Python `or` 合并
   四层配置的候选 patch。
2. **Sender noise：** 配置库比较、生产环境变量样本、旧优先级方案和无关 deployment diff。
3. **Required state：** `constraints` 给出 `FALSY_OVERRIDE` acceptance ID 和“仅 `None` 缺失”
   规则；`evidence` 展示 CLI `timeout=0`、`debug=False` 被低层值覆盖的 trace；`artifacts`
   标明 candidate diff；`tool_results` 包含普通 truthy case 已通过；`pending_work` 是 review。
4. **Receiver output contract：** 输出统一 reviewer JSON，不提供修复代码。
5. **Success validator：** 对 candidate 运行 falsy matrix，并以失败 acceptance rule 生成 oracle；
   该 fixture 要求 `request_changes` 且 blocker set 恰为 `FALSY_OVERRIDE`。

### RR-03 Review a complete Retry-After patch

1. **ID / 方向 / 真实任务：** `RR-03`，researcher → reviewer；审查一个声称完整支持
   `Retry-After` 两种格式的候选 patch。
2. **Sender noise：** 较早的 integer-only diff、重试策略长文、HTTP client 迁移计划和大量无关
   access log。
3. **Required state：** `constraints` 给出 DELTA、HTTP_DATE、CLAMP、INVALID 四条 acceptance
   rule/ID；`evidence` 是冻结 now 的边界表；`artifacts` 标明最终 candidate diff；
   `tool_results` 是公开用例结果；`pending_work` 要求独立审查。
4. **Receiver output contract：** 输出统一 reviewer JSON；只有所有 acceptance rule 均满足时才
   `approve`。
5. **Success validator：** 对最终 candidate 运行独立 table/reference comparison，并据失败项
   生成 oracle；该 fixture 的 candidate 通过全部规则，因此预期 `approve` 和空 blocker list，
   该预期不计作 provider 结果。

### RR-04 Review a manual CSV splitter

1. **ID / 方向 / 真实任务：** `RR-04`，researcher → reviewer；审查用 `splitlines()` 和
   `split(",")` 实现 CSV import 的候选 patch。
2. **Sender noise：** Excel UI 需求、导出 benchmark、未采用的 pandas spike 和普通无逗号样本
   的长通过日志。
3. **Required state：** `constraints` 给出 `CSV_QUOTED_FIELD`、`CSV_MULTILINE_RECORD` 和其他
   acceptance ID；`evidence` 包含 quoted comma 与 quoted newline fixture；`artifacts` 标明
   candidate diff；`tool_results` 说明简单样本通过；`pending_work` 是 merge verdict。
4. **Receiver output contract：** 输出统一 reviewer JSON，并列出所有被违反的 acceptance ID。
5. **Success validator：** 在 candidate 上运行每条 acceptance probe 并构造 expected set；该
   fixture 预期 `request_changes`，blocker set 恰为 `CSV_QUOTED_FIELD` 和
   `CSV_MULTILINE_RECORD`。

### RR-05 Review a package-data fix

1. **ID / 方向 / 真实任务：** `RR-05`，researcher → reviewer；审查一个修复 wheel/sdist
   template 遗漏的候选 patch。
2. **Sender noise：** 早期绝对路径 workaround、Docker/PyInstaller 记录、其他 package 的构建
   日志和文档站部署讨论。
3. **Required state：** `constraints` 给出 WHEEL_CONTENT、SDIST_CONTENT、RESOURCE_READ、
   IMPORT_SMOKE 四条 acceptance rule；`evidence` 是原失败复现；`artifacts` 标明最终 build
   config diff 和 template；`tool_results` 包含本地 build 日志；`pending_work` 要求 review。
4. **Receiver output contract：** 输出统一 reviewer JSON，不重写 packaging backend。
5. **Success validator：** 从 clean checkout 构建两个 archive、安装 wheel、从不同 cwd 读取
   resource 并 import；由这些 probe 生成 oracle。该 fixture 的 candidate 全部通过，预期
   `approve` 和空 blocker list。

### RR-06 Review resumable checkpoint behavior

1. **ID / 方向 / 真实任务：** `RR-06`，researcher → reviewer；审查 batch checkpoint 的
   最终候选实现。
2. **Sender noise：** 一个“执行前先 checkpoint”的旧 diff、并行队列规划、云 checkpoint 方案
   和无关吞吐日志。
3. **Required state：** `constraints` 给出 AFTER_SUCCESS、NO_SKIP_AFTER_FAILURE、ATOMIC_FILE、
   ORDER 四条 acceptance rule；`decisions` 是成功后落盘并原子 replace；`evidence` 给出 C 首次
   失败的期望 trace；`artifacts` 唯一标明最终 candidate diff；`pending_work` 是 review。
4. **Receiver output contract：** 输出统一 reviewer JSON；不得把旧 diff 当成当前 candidate。
5. **Success validator：** 对最终 candidate 注入 C 首次失败并检查两轮 call sequence、checkpoint
   JSON 与残留临时文件，再生成 oracle。该 fixture 的 candidate 满足全部规则，预期
   `approve` 和空 blocker list。

## 落地顺序建议

先实现每类各一个 pilot：`RC-01`、`PE-01`、`RR-01`。只有 pilot 的 sandbox、三种输入构造、
provider runner、token/event 记录和 validator 全部跑通后，再批量实现其余 17 项。每个任务的
validator oracle 必须来自可执行行为或精确产物比较，不能来自模型自评，也不能在正式结果中
用上述“预期”代替真实 run。

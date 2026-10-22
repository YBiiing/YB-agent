# V2 本地审计格式

P1-09a 实现归档读写基础，P1-09b1 通过显式 --archive-dir 接入执行循环及 CLI，只读 --inspect-archive 用于查询；P1-09c 提供证据分层及有界验收判定。本格式只保存可检查的本地记录，不提供恢复、调度或动作重放接口。

## 写入与文件

`RunArchive(parent, run_id, project, sanitize=model.sanitize)` 要求现有可信父目录位于项目外，以本次 32 位十六进制 Run ID 创建新子目录。已有同名目录拒绝，不覆盖历史 Run。目录和文件拒绝链接／reparse，文件要求普通文件且只有一个硬链接。用户应保护父目录写权限；这些检查不是针对同权限恶意进程的 OS 隔离。

`checkpoint(report, artifacts=(), final=False)` 保存以下内容：

- `report.json`：版本化的完整运行报告，保留原始工具观测，不使用发给模型的压缩副本。
- `events.jsonl`：每行 schema_version、run_id 和事件；sequence 从零连续递增。每次检查点必须保留已有事件前缀。
- `artifact-<id>.txt`：调用者提供的完整有界输出，绑定来源 SHA-256 及原始输出截断属性。同一 ID 不允许重新绑定或在后续检查点遗漏。
- `manifest.json`：schema_version=1、Run ID、从零递增的检查点 generation、OPEN／FINAL、事件数、全部文件的字节数及 SHA-256、制品来源摘要和脱敏信息。

每文件最多 4 MiB，数据文件合计最多 16 MiB，事件最多 4096，制品最多 128。超限给出明确错误，不静默截断。制品原始内容已被硬上限截断时，保存内容完整并不代表原始命令输出完整。

对象字符串先经模型适配器脱敏，再编码或创建临时文件。该机制处理本次适配器已知凭据及其转义形式，不保证自动识别任意项目文件内的未知秘密；敏感文件读取仍由工具策略限制。额外脱敏改变制品内容时，来源摘要和保存摘要分别保留；未改变时两者必须一致。哈希用于一致性检查，不是签名或认证。

每个文件先在同目录唯一临时文件写完、flush／fsync，再替换目标文件；manifest 最后提交。多文件更新不是事务，中途失败可能令目录不完整，writer 随即关闭。它不承诺断电／强杀前最后一次检查点或目录项已经持久化。

## 只读查询

```python
from pathlib import Path
from src.v2.archive import read_archive

result = read_archive(Path(r"E:\path\to\audit\本次run_id"))
```

查询检查 schema、固定文件集合、文件大小／摘要、事件序号、JSONL 与报告的一致性、制品来源，以及读前读后的 manifest。一旦缺失、截断、损坏、格式不支持或读取失败，返回 `integrity=INCOMPLETE` 和安全错误码，不返回一份看似完整的 report。读取不会修改档案或启动任何动作。

`integrity=VERIFIED` 仅表示这份记录通过了上述一致性检查，不能替代任务验收。`record_status=FINALIZED` 包括正常完成、失败、取消和预算耗尽；它不等于 PASSED。OPEN 清单显示 `UNFINISHED_OR_INTERRUPTED`，因为仅凭磁盘记录不能区分仍在运行与异常退出。异常记录需要人工检查可能的副作用，不自动续跑或清除残留进程。


## Evidence 与 Assessment

运行报告的 `assessment_details` 保存 criterion 表、证据表、未决事项，以及判定时提供的 current_versions。`MODEL_CLAIM` 引用已接受的模型最终决定；`TOOL_OBSERVATION` 引用 Step／Call、执行状态和原输出摘要，只能表明取得了观测。二者没有 criterion outcome；工具输出里的 JSON 即使自称“独立验证通过”，也不会变成验证记录。

`INDEPENDENT_VALIDATION` 由可信应用验收器通过 Python API 提供，必须明确当前 Run、criterion、验收器引用、检查范围、PASSED／FAILED／INCONCLUSIVE 和至少一项资源 SHA-256。证据不可变，所有 ID 全局唯一；跨 Run、未声明条件或重复引用拒绝。模型没有写入该类型的工具，也不能通过普通工具输出声明权限。

`assess(run, criteria=..., validations=..., current_versions=...)` 只进行计算，不读取路径、执行新命令或解释自然语言判据。调用者负责独立产生检查结果并提供实际观察到的资源快照。引用可为 workspace:相对文件名、answer:RunID 等；哈希只能支持列出的版本与范围，不能自动覆盖未声明依赖或语义正确性。检查文本或命令退出零的意义由该验收器的明确判据决定。

新鲜度按给定快照区分 CURRENT、STALE_OR_UNAVAILABLE、NOT_CHECKED 和 UNBOUND。旧验证或资源缺失不能支持通过；之后文件改变时，使用新的实际哈希再次判定，旧验证将失效。磁盘查询只读取归档时记录的快照，不重新读取当前项目，不能把历史 CURRENT 解释成“现在仍有效”。

每个条件只接受 CURRENT 的独立验证：明确失败优先；明确无法判断则 INCONCLUSIVE；没有有效独立验证则 UNVERIFIED 或因旧／未核对验证而 INCONCLUSIVE。旧版本失败仍保留，但不覆盖针对新版本的有效检查。同一条件多个当前结果有冲突时，不能以多数通过消除失败。

总体必须满足至少一个必需条件且全部必需条件有有效通过证据才可能 PASSED；任一必需条件有效失败则 FAILED，其余已有部分通过但缺少必需证据时 PARTIAL。可选条件逐项展示，不阻断已满足的必需条件。工具 UNKNOWN、未观测调用、未结束 Run 或在途执行留在 unresolved，阻止总体 PASSED；已知必需失败仍可报告 FAILED，并同时保留未知事项。

普通 CLI 目前没有配置自然语言目标的独立验收器，因此正常结束仍为 UNVERIFIED；UNKNOWN 为 INCONCLUSIVE。`RunController.assessment` 保留运行层的 UNVERIFIED，报告的判定与执行状态分开计算。冻结任务的独立评测脚本继续使用其已固定的具体判据与报告；不能把这套通用证据模型当作通用自然语言正确性验证器。

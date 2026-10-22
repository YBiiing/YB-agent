# V2 本地审计格式

P1-09a 实现归档读写基础，P1-09b1 通过显式 --archive-dir 接入执行循环及 CLI，只读 --inspect-archive 用于查询；Evidence／Assessment 判定在后续切片完成。本格式只保存可检查的本地记录，不提供恢复、调度或动作重放接口。

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

# 第一阶段固定评测规范

数据版本：1。冻结时间：2026-10-21，早于首次 V2 真实模型请求。输入与判据见 [tasks.json](tasks.json)。

这是一组范围有限的合成项目验收，不用于宣称通用 Coding Agent 成功率。每个样本在全新临时目录展开，目录中只包含清单规定的文件，不向供应商发送真实项目或凭据文件。

## 样本、用途与次数

| 类别 | 开发基线样本 | 最终验收样本 | 每个样本重复次数 |
| --- | --- | --- | --- |
| 只读调查 | read-dev-01 | read-final-01 | 2 |
| 失败反馈后的修复 | repair-dev-01 | repair-final-01 | 2 |
| 受约束多步检查 | inspect-dev-01 | inspect-final-01 | 2 |

开发样本可以调优；所有尝试均保留且注明配置版本。各类第一份基线是该类相同配置的连续两次运行，不能只挑成功一次。只读基线在 P1-04；修复、检查基线在 P1-06。开发和最终合计最低 12 次 Run，每次单独受预算限制；每批最多 2 个 Run，最多 12 次实际请求，不无限追加批次。

最终样本可静态检查格式与判据，首次真实 Agent 执行必须等到 P1-12，且三类门槛已冻结。最终每类连续执行两次，不因失败追加替代样本或只挑最好结果。依据最终失败改动提示词、代码、预算或样本后，必须递增评测版本、记录原结果并重新开展全部最终评测；不得混用调优前后结果。相同版本的最终失败保留在报告中。

## 每个 Run 的硬上限

- 6 个 Step、6 次实际模型请求（包括所有重试）、12 次实际工具执行；任何 SDK 隐式重试关闭。
- 单次输出 `max_tokens=1024`；每次模型输入的完整序列化 payload 最多 16384 UTF-8 bytes，包含工具定义；不在截断的 tool-call 组上发送请求。
- 累计 Token 预算 131072。发送前按输入字节数加保守协议余量 1024、最大输出 1024 预留；供应商返回可靠用量时结算，否则保留预留并标记未知。此为选定兼容模型的保守治理规则，不声称提供供应商精确 tokenizer。
- 运行截止 180 秒，单次模型等待 45 秒，单次本地工具执行 5 秒；命令停止清理的等待共用额外两秒截止，OS 调用及调度时间另计，不在截止后派发新动作。审批等待与执行预算的细化在 P1-07 完成前冻结。评测使用预先批准的合成项目动作范围，无交互等待。
- 文件每次读取最多 16384 bytes。输出、上下文和工具机制变更导致样本无法在预算内运行时，记录失败；不能悄悄提高限制。
- 每批执行前打印样本、次数和上限；每个实际请求、失败、未知用量和耗时都必须入档。用量未知不能记为零。

## 必需验收条件

所有类别都要求 Run 正常交付、无 UNKNOWN、未违反路径/修改限制、证据对应当前文件版本，且实际成功读取 required_reads 的全部文件。带 expected_exit 的检查必须精确匹配实际退出码；带 success_marker 的样本，标记必须出现在对应成功检查的实际输出中（包括独立复验），不能只来自模型文本。独立验收器在 Agent 外判定；模型的最终声明不能直接生成 PASSED。

- **只读调查**：实际成功读取 `required_reads` 的每个文件；最终答案包含 `facts` 全部字段值及其来源路径；所有初始文件哈希不变，且未创建其他项目文件。仅输出猜测答案不通过。
- **修复**：先运行指定 `check.py` 并观察非零退出，修改后再运行同一检查并观察零退出；仅允许修改 `allowed_changes`。独立进程还需对最终文件重新运行检查；最终检查前后被测文件哈希一致。不能修改检查脚本或仅报告“测试通过”。
- **多步检查**：实际读取全部 `required_reads`，运行规定检查，最终结果包含全部 `facts` 与检查发现；项目文件完全不变。样本本来包含违规数据，检查非零退出是观测事实，不能被写成“全部通过”；任务成功指准确发现和报告该违规。

清单中 `files` 是准确 UTF-8 内容，按字节写入，避免宿主平台自动改变换行；`facts` 不是模型提示词的一部分。验收脚本不能由 Agent 编辑。

## P1-06 开发基线执行边界

`scripts/run_v2_action_baseline.py --category repair|inspect --runs 1|2` 仅选择相应 development 样本，不能选择 final。每次在独立空工作区展开；动作仍经过审批记录及许可前复查，自动批准只适用于用户已授权的这组有界合成样本，硬拒绝不能被批准覆盖。

为避免把模型生成的任意代码直接交给当前非沙箱执行器，修复开发样本的命令前置条件额外限定为：检查脚本字节不变，`calculator.py` 仅含可选文档字符串及 `add(a,b)`，返回参数之间的加／减表达式；禁止其他可执行结构。只接受 UTF-8 源编码，AST 直接解析原始字节，与 Python 导入语义一致。检查开发样本的全部文件保持原样。此限制不是通用 Python 沙箱；其他等价但范围外的正确实现也可能被拒绝，仍记录为该次失败，不剔除尝试或据此宣称一般修复能力。

验收器核对读取顺序、所有声明输入哈希、输出制品大小／SHA、检查前后文件一致、失败—写入—成功的顺序与哈希链。命令非零退出是实际观测；inspect-dev-01 的预期值为 1。只有正常交付、证据有效且安全前置条件成立才启动 Agent 外的独立检查；取消、UNKNOWN 或无当前检查证据均不触发新的进程。归档分别尝试保存 Run 和供应商记录，任一失败仍在 summary 保留已发生的请求及计费，整次按失败处理。

检查开发基线采用 `inspection-json-v1` 输出约束，在首次真实执行前固定为 Task.constraints，原 task 和 files 不变，不向模型提供事实答案。最终文本仅为 JSON 对象，准确字段为 `check_exit_code`、`verdict`（`issues_found` 或 `passed`）、`findings`；每项 finding 仅有 `code`、`subjects` 和整数 `value`。验收器从冻结配置独立推导冲突对象／端口，逐项核对结论，拒绝重复 JSON key、额外字段或自然语言附言。出现事实词却声称“全部通过”的矛盾文本不能通过；不尝试凭关键词评价任意自由文本语义。该格式约束也进入请求／配置归档，尚未运行的最终评测采用何种输出契约应在其首次执行前明确。

## 分类门槛冻结表

| 类别 | 基线与数值门槛 | 冻结时点 |
| --- | --- | --- |
| 只读调查 | 开发基线 2/2；最终至少 2/2（100%），必需机制全部通过。理由及原始证据见 results/read-baseline-v1/REPORT.md | 2026-10-21，P1-04 基线后冻结，早于最终样本执行 |
| 失败反馈后的修复 | 开发基线 2/2；最终至少 2/2（100%），必需机制全部通过。理由与证据见 results/repair-baseline-v1/REPORT.md | 2026-10-21，P1-06 同类基线后、最终样本执行前 |
| 受约束多步检查 | 开发基线 2/2；最终至少 2/2（100%），必需机制全部通过。理由与证据见 results/inspect-baseline-v1/REPORT.md | 2026-10-21，P1-06 同类基线后、最终样本执行前 |

门槛至少包含最终两次中的最低成功次数和比率，并有同类真实成功案例要求。三个数值未冻结则 P1-06/P1-12/G1 不能通过。不能看到最终结果后降低门槛。Windows 是当前实际运行环境；Linux 未验证，不据此宣称跨平台行为已经通过。

## P1-12 最终执行协议（首次真实最终执行前冻结）

`final-v1.json` 固定 evaluation_version=phase1-final-v1、原 dataset_version=1 及清单 SHA、模型配置、完整 Limits、三类各 2 Run／每类必须 2/2。每批最多 12 请求、整套最多 36 请求，单次最多 1024 输出 tokens，模型重试 0。清单与样本内容、原 task、facts、重复次数和分类门槛没有修改。

清单实际开发基线均使用 SHA `9c41f4f372b1a23cc5aaf1e176a1bbf0a14e7d8f425f52cc525bcc7fa1f3ee9a` 的 CRLF JSON 文件；Git 旧属性可能将它在其他环境检出为 LF。为保持已冻结字节，`evals/v2/.gitattributes` 对 tasks.json 和 final-v*.json 禁止行尾归一化。此为容器 JSON 字节策略，内部 files 字符串及展开的 UTF-8 文件内容不变；不能临时忽略摘要差异或改 hash 绕过校验。

最终入口：

```powershell
python scripts/run_v2_final.py --config E:\path\to\config.yaml --category read
python scripts/run_v2_final.py --config E:\path\to\config.yaml --category repair
python scripts/run_v2_final.py --config E:\path\to\config.yaml --category inspect
```

每次固定连续两次，不接受 --runs 或提高额度的参数。执行前要求工作区已提交；同一个 suite 绑定 Git HEAD、全部 V2／评测脚本摘要、协议、模型设置和关键运行依赖版本，跨类别配置变化拒绝混用。输出为 `.harness/phase1-final-evals/phase1-final-v1/<category>`；类别目录已存在时拒绝覆盖／补跑，即使先前失败也保留。能力失败继续记录第二次；环境、归档或协作中断保留已开始尝试与请求／未知费用，不将未完成类别计为通过。最终失败若导致实现或配置修订，应创建新评测版本并重新执行全部最终类别，旧结果保留，不能降低 2/2 门槛。

read-final-01 保持原任务及事实／来源／全文件不变判据。repair-final-01 的 check.py 字节不变；labels.py 只允许 normalize_label(text)、可选文档字符串、最多八条局部赋值及一个 return。表达式仅包含输入／局部内建字符串、有限字符串／整数常量、strip／upper／lower／replace／split／join 的有限静态类型调用；没有导入、任意函数、反射、循环或推导式。该语言允许安全但错误的实现，由实际检查判定正确性；不是答案白名单或 OS 沙箱，其他正确但范围外的实现仍可能被拒绝并记为失败。

inspect-final-01 在首次真实执行前固定 `inspection-retries-json-v1`：最终只输出 check_exit_code、verdict、findings，每项 finding 只含 code、subjects、value（实际次数）、limit（文档上限）。字段含义由 Task.constraints 提供，不提供 beta／5／3 等答案；验收器从冻结 README／limits.json 独立推导，逐项核对计数、上限、对象、问题代码和非零退出，拒绝重复键／附加文字／矛盾 passed。它没有复用开发样本的端口冲突判据。

final 模式显式接入本地审计，派发及观测遵循同一 Engine 规则；审计失败不能得到独立 PASSED。action 仍需读全文件、取得可靠当前检查、遵守修改范围与顺序，并在正常且无 UNKNOWN 后执行外部独立复验。运行审计保存内部 UNVERIFIED；具体独立结论保存在每次 run-XX.json 的 independent_assessment，不能把两者混为一谈。原开发入口仍只选择 development，不自动开启 final。

## P1-12 v2：已见固定样本的能力约束披露重评

首次 v1 结果为 read 2/2、repair 0/2、inspect 2/2，完整证据保留于 results/final-v1，G1 未通过。两次修复均使用 import re，超过已存在的 AST 能力范围；Task 未披露该范围，修改后检查被拒绝。v2 只修复任务信息契约，不改执行 guard、验收器、清单、预算或 2/2 门槛，也不提供具体实现答案。

`final-v2.json` 显式绑定 repair_task_contract=bounded-string-capabilities-v1 及文本 SHA，reevaluation_of=phase1-final-v1。约束文本披露函数／赋值／return 结构、静态类型、方法签名、常量与深度限制、禁止导入／反射／控制流等既有边界。v1 协议不接受新契约字段，原 repair Task 仍无附加约束；开发入口不接收此 final 契约。协议冻结字段改为 frozen_before_first_real_version_run，只指 v2 首次执行前冻结，不声称从未查看过最终样本。

使用下列命令分别执行三类；默认入口仍选择历史 v1，不会静默改用 v2：

```powershell
python scripts/run_v2_final.py --config E:\path\to\config.yaml --protocol evals/v2/final-v2.json --category read
python scripts/run_v2_final.py --config E:\path\to\config.yaml --protocol evals/v2/final-v2.json --category repair
python scripts/run_v2_final.py --config E:\path\to\config.yaml --protocol evals/v2/final-v2.json --category inspect
```

新 suite 独立保存在 .harness/phase1-final-evals/phase1-final-v2；全部三类六 Run 重跑，不复用 v1 成功项。每 Run 最多六请求、单次输出 1024 tokens、运行 180 秒，整套最多 36 请求；失败占用该版本类别，不覆盖或补挑最佳结果。v1 永久保持原失败结论。即使 v2 全部通过，也仅支持已见固定样本上的约束披露改进与回归验证，不构成未见样本泛化证明。

## P1-12 v3：公开工具与固定策略一致

v2 实际结果 read 2/2、repair 1/2、inspect 2/2，完整失败保留于 results/final-v2。第二次修复已有可靠修改后检查，但模型继续调用公开的 read_artifact，超出 fixture 策略与验收范围而失败。v3 仅在最终评测 runner 投影模型可见工具，不改通用工具、原 fixture 策略、AST guard 或独立验收器，不将历史失败改判。

`final-v3.json` 绑定前版 v2、有序精确 offered_action_tools=[read_file,write_file,run_command]，复用 v2 能力说明及摘要。runner 从真实注册定义选取完整 schema，缺失或重复注册失败关闭，不自行重写参数定义。v1／v2 仍向模型提供历史四工具；v3 只有三工具。公开定义不是授权：即使供应商返回隐藏工具调用，原硬规则仍拒绝，范围验收仍失败，不执行独立复验。制品的完整保存／审计不受模型可见定义影响。

执行方式与 v2 相同，将 --protocol 改为 evals/v2/final-v3.json。默认协议继续为 v1；新 suite 为 .harness/phase1-final-evals/phase1-final-v3。任务清单、三类各两次、2/2 门槛、每 Run 六请求／单次输出 1024 tokens／180 秒、全套 36 请求上限全部不变。提交冻结后完整重跑六 Run，不挑类别、混用旧成功或事后放宽拒绝。v3 仍为已见固定样本上的接口修订回归，不能证明未见任务泛化。

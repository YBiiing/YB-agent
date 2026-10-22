# V2 当前使用方式

当前已实现只读循环、受控版本写入、Windows Python 检查、离线 mock 和 DeepSeek 适配。调查／修复／检查三类真实开发基线均已连续两次通过独立检查，证据见 `evals/v2/results/*-baseline-v1/REPORT.md`；最终样本尚未执行，第一阶段其余能力按 PHASE1_PLAN.md 继续实施，不能将当前结果视为 G1 完成。

## 安装与离线演示

从仓库根运行 `python -m pip install -e .`，然后：

```powershell
harness-v2 --project E:\path\to\trusted-project --task "只读演示" --model mock --read-file first.txt --read-file second.txt
```

也可以用 `python -m src.v2` 代替已安装入口。mock 按指定顺序读取并总结实际状态，只用于验证执行机制；它不会理解任意自然语言任务。未配置真实模型时不会静默切换到 mock。旧入口 `harness` 保留。

若本机配置了 SOCKS 代理，使用 `python -m pip install -e ".[proxy]"` 安装 HTTP 客户端代理依赖。`MODEL_PROXY_DEPENDENCY_MISSING` 表示请求尚未发出即缺少该依赖；不通过关闭代理或改变系统网络设置解决。

## DeepSeek 只读任务

显式提供已有 YAML 配置，其中 `llm.provider` 为 `deepseek`、`llm.model` 与参数一致、`llm.base_url` 为官方 HTTPS 地址（可含 `/v1`）。V2 仅读取模型选择和地址，不继承旧配置中更高的 Token 或循环额度，不自动应用旧环境变量覆盖。凭据从 `harness key set` 使用的系统 keyring 身份读取，缺失时读取 `HARNESS_API_KEY` 环境变量；不自动读取项目 `.env`。

```powershell
harness-v2 --project E:\path\to\synthetic-project --task "从 README.md 的入口逐步调查配置，给出来源路径和结论" --model deepseek-chat --config E:\path\to\config.yaml
```

默认使用原生工具调用。需要兼容 JSON 决策时显式添加 `--format json`。每个 Run 默认至多 6 次模型请求（含重试）、6 Step、12 次工具执行；SDK 内部重试关闭。单次输出最多 1024 tokens，完整输入最多 16384 UTF-8 bytes，累计 Token 预算 131072，运行截止 180 秒，模型单次等待 45 秒。`--max-steps 1..6` 可下调步骤上限。

请求预算预留不等于供应商精确计费；已知用量按响应结算，未知用量保留保守预留并明确标记。Token 超限、截断输出、认证/协议/传输错误均不会被当作正常最终回答。API 错误原文及凭据不写入报告。

`--model-retries 0..2` 设置每个尚未接受 Decision 的模型决策的外层重试次数，默认 0，保留既有基线配置。仅对 429、5xx，以及已完整收到且有有效用量的协议错误重试；认证失败、其他 HTTP 错误、连接错误、超时、输出截断和用量未知的协议错误不重试。重试是一次新的模型生成，可能再次计费、产生不同回答，不用于推断前次超时请求的结果。SDK 内部重试仍为 0。

每次重试重新准备完整输入、预留 Token、取得模型许可并记录独立 Attempt，仍受每 Run 六请求和累计 Token／总时限约束；未知费用预留不会释放。第 1／2 次重试分别等待 0.25／0.5 秒，状态为 WAITING／MODEL_RETRY，期间暂停／取消仍有效；继续仅重发尚未成功取得有效决策的请求，不重发已经缓存的有效响应。工具没有因此增加自动重试，UNKNOWN 工具仍立即终止并保留未决事项。

默认工具集仅开放项目内受控 UTF-8 文件读取，单文件最多 16384 bytes；隐藏分段、敏感名称、绝对/父目录/ADS/设备/短名路径、链接和硬链接会被拒绝。这是面向可信受控项目的防护，不是操作系统沙箱，不保证对并发恶意文件系统安全。当前仅实际验证 Windows；Linux 未验证。任意名称中含 `~` 也会保守拒绝。

## 输出与限制

DeepSeek 输入按完整序列化 payload 的 UTF-8 bytes 计量。内容能放下时不改变请求；超限时先机械压缩长工具观测，保留头尾片段、原输出 SHA／字节数、错误状态、资源版本及制品 ID 等关键元数据；仍超限则按最旧顺序省略完整 Step 调用／响应组，始终保留最近完整组。目标、任务约束、验收条件、系统规则和工具定义不会因此删改。所有改动在输入中的 runtime_context_manifest 明确列出省略 Step 和压缩调用及原哈希，模型可按需重新读取来源／制品。

这不是语义记忆，也不保证被省略的旧事实无用。不能安全放下必要上下文时，以 EXHAUSTED／MODEL_INPUT_LIMIT 结束，不拆批次或发送孤立 tool response；未闭合或含 UNKNOWN 的组不接受为模型上下文。原 Run／报告保留完整 Decision 和 ToolResult，压缩只影响模型输入副本；外部文字仍以 external_tool_observation 或 external_tool_observation_summary 标注，不能提升权限或预算。当前仅 DeepSeek 适配器使用该机械构建器，自定义适配器仍必须通过 Engine 的最终输入预算检查。

stdout 输出 JSON 报告，含 Run/Step/Decision/调用/观测/尝试/事件及模型用量。退出码 0 表示运行正常交付，1 表示未正常交付，2 表示配置或参数错误。`COMPLETED` 不等于目标验收 `PASSED`；当前 Assessment 保持 `UNVERIFIED`。完整持久审计与正式独立验收由后续小目标交付。

审批机制已接入启动边界：默认 `--approvals deny` 对需要人类批准的动作返回拒绝反馈；`--approvals interactive` 展示具体动作，输入 `yes` 批准、`cancel` 取消，其他输入（包括 EOF）拒绝。审批绑定当前 Run、主体、动作参数/版本、可信资源事实、策略版本和期限；资源变化或过期会重新申请，硬拒绝不能被批准覆盖。

默认 `--tools read`。显式 `--tools workspace --approvals interactive` 增加 `write_file(path, content, expected_sha256)`，模型必须提供读取时的内容 SHA-256，新文件使用 `MISSING`。只在已有目录内写入，内容为有界 UTF-8；敏感路径、链接、范围外路径仍拒绝。执行前与提交前重新核对版本，既有文件暂存后替换，新文件无覆盖发布。结果不明标记 `UNKNOWN` 并终止，不自动重试；线程超时不代表底层写入已经停止。

写入面向受控单写者工作区，哈希检查与替换不是抵御不合作外部写者的原子条件写入，也不保证崩溃后的持久恢复。当前读取授权事实使用路径及 stat 版本，写入使用真实内容哈希。

## 运行中的控制

显式 `--control-file` 开启本地操作员 JSONL 通道。文件必须位于项目外，父目录已存在，不能是链接、junction、硬链接或特殊文件；不存在时创建空文件，已有文件不会被清空。它是当前进程的控制输入，不是崩溃恢复日志；本机用户应保护其写权限，不应把它放到不可信共享目录。

```powershell
harness-v2 --project E:\path\to\trusted-project --task "调查项目" --model mock --control-file E:\path\to\operator.jsonl --start-paused --run-seconds 180
```

stderr 持续输出逐行 JSON 状态和控制回执，stdout 保持最终 JSON 报告。首条状态给出本次 `run_id`；`--start-paused` 确保首个模型请求前等待 `resume`，仅可结合控制文件使用。在另一个 PowerShell 终端用得到的真实 ID 追加一整行（UTF-8、无 BOM、以换行结束）：

```powershell
$controlPath = 'E:\path\to\operator.jsonl'
$runId = '从 control_status 复制本次 run_id'
$record = @{run_id=$runId; command='resume'} | ConvertTo-Json -Compress
[IO.File]::AppendAllText($controlPath, $record + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
```

command 可为 `pause`、`resume`、`cancel` 或 `status`。按文件顺序处理，其他 Run 的指令忽略；终态不会被重新调度。`resume` 只在已进入 PAUSED 后接受，在途暂停请求还未落地时返回 `CONTROL_NOT_READY`，应等状态再操作。取消请求优先于后来的暂停或继续。

写入／命令审批需显式 `--approvals control-file`；状态包含当前审批 ID、动作参数、资源版本和要求。追加 `{"run_id":"本次ID","command":"approve","approval_id":"当前审批ID"}`，或将 command 改为 `deny`。只接受当前等待的审批，执行前照常重查全部策略、资源与有效期；默认 deny 模式不会因为控制文件里的 approve 而开放写入。控制文件不能与 `--approvals interactive` 同时使用。

文件上限 65536 bytes、每行 2048 bytes、最多 128 条非空指令；不完整末行等待换行，格式错误行给出安全回执，不回显原文。运行期间只允许追加；重写、替换、文件丢失、超限或读取失败会取消 Run 并阻止后续派发，已有在途动作按原协议收尾。每次运行宜使用新的控制文件。项目外路径可阻止文件读写工具直接访问控制通道，但已批准的 Python 仍有本机用户的文件权限；这不构成抵御任意项目代码的隔离边界。

控制轮询间隔为 50ms，实际响应受 OS 调度和短同步操作影响。模型在途取消会等待有界响应或超时，保留计费信息、丢弃迟到决策；不会声称供应商停止计费。命令取消会请求停止 Job 并等待确认，停止不明仍为 UNKNOWN。暂停等待在途动作收尾，保留有效模型响应及未执行调用；继续不会重复已观测调用或有效模型请求。`--run-seconds 1..180` 计入执行、审批和暂停等待，截止后不发新动作；进程清理另有既定有界等待。

`--approval-seconds 1..180` 与 `--pause-seconds 1..180` 分别限制本 Run 累计等待审批／实际暂停时间，默认各 60 秒，分别耗尽时报告 APPROVAL_WAIT_LIMIT／PAUSE_WAIT_LIMIT。多次等待、暂停继续不会重置额度；在途动作尚未收尾的暂停请求不算已暂停，退避时间也不混入审批等待。单次模型／工具执行时限继续单独计量，总墙钟截止始终有效。

交互审批使用非阻塞轮询读取，Windows 控制台保留 Enter、退格和取消键；管道／文件输入按有界 UTF-8 行读取。每行最多 256 字符（控制台）或 bytes（管道），超长行拒绝并丢弃至换行，不将尾部误作下一次批准。EOF 拒绝，不可用输入报告 OPERATOR_INPUT_UNAVAILABLE；无人输入时仍检查等待／总截止，不启动阻塞输入线程。真实 Windows 管道及保持 stdin 打开的子进程截止已验证；控制台编辑键通过模拟回归，尚未做手动真实键盘验收。

当前已在 Windows 验证外部 CLI 继续／截止，以及模型等待、批次暂停、审批取消和真实命令取消；Linux 尚未验证，不宣称其平台行为已通过。

## 受控 Python 检查（Windows）

显式 `--tools commands` 提供读取、版本写入和 `run_command(program, args)`。当前 program 只接受 `python`，固定映射本解释器；args 仅包含一个通过 `--command-script` 列入范围的相对 `.py` 路径。原始 Shell、任意可执行程序、解释器选项及脚本额外参数均未开放。

```powershell
harness-v2 --project E:\path\to\trusted-synthetic-project --task "先运行 check.py 观察失败，修复后再检查" --model deepseek-chat --config E:\path\to\config.yaml --tools commands --command-script check.py --command-input calculator.py --artifact-dir E:\path\to\v2-output --approvals interactive
```

每个命令都会重新审批，绑定脚本和显式 `--command-input` 文件的内容哈希（最多 64 个声明输入），启动时再次核对；脚本自动作为输入。必须自行声明间接依赖与数据文件，这不是自动完整依赖分析。制品目录必须在项目外，防止检查输出污染项目文件；输出以唯一文件名保存，不覆盖既有制品。

命令默认 5 秒，有界组合 stdout/stderr 最多 65536 bytes，超限终止进程树；保存完整的有界 UTF-8 输出（非法序列替换、已知凭据脱敏）及 SHA-256，模型反馈含最多 4096 字符的头尾预览、退出码、输入前后哈希和制品路径。达到硬上限的输出不宣称完整。非零退出表示检查发现问题或程序失败，工具的 `SUCCESS` 仅表示取得可靠执行观测，须查看 `exit_code`。

命令反馈同时给出本 Run 的 `artifact_id` 与 `stored_bytes`；commands 工具集增加 `read_artifact(artifact_id, offset, length)`，offset 为从 0 开始的字节偏移，length 为 1..4096 bytes。查看尾部可选择 `max(0, stored_bytes-length)`；返回内容、下一偏移、制品 EOF、完整内容 SHA 和原始输出截断标记。字节页切在 UTF-8 字符中间会替换不完整字符，返回值明确说明编码，必要时调整偏移重读。

该工具只读本工具执行器在当前 Run 注册的脱敏输出，不接受模型传入文件路径或任意目录，也不扫描既有制品目录。每次读取核对完整制品哈希和大小，内容变化不返回页面；链接／硬链接／reparse 拒绝。读取仍计入工具调用和时间预算，无须额外写入审批；历史制品不会因重启重新获得可执行 ID。CommandTools 实例绑定单个 Run，新 Run 应创建新执行器，以免跨 Run 暴露制品。制品 EOF 只表示读到已保存内容的末尾，`original_output_truncated=true` 时不能视为取得完整原始命令输出。

隔离 launcher 加入 Windows Job 后才启动项目脚本；Job 不开启 breakaway，限制 16 个活动进程和 256 MiB 内存。子进程环境不继承模型 API 凭据，启用 UTF-8 并禁写 bytecode。超时／取消后尝试停止整棵进程树并确认 Job 无活动成员、已采样进程句柄退出；未采样短命进程的内核对象仍可能稍后清理。清理等待共用两秒额度，OS 调用及调度另计。无法确认停止或执行后的证据保存失败会报告 `UNKNOWN` 并终止 Run；不自动重试。

停止确认不等于撤销副作用，反馈始终说明已启动命令可能产生副作用，非零退出同样如此。此能力只适用于可信受控代码；项目 cwd、输入声明、最小环境和 Job 都不能限制任意代码访问文件、网络或系统权限。当前仅验证 Windows，Linux 命令拒绝执行。监管依据为 [Microsoft Job Object API](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)。

离线回归统一使用 `python scripts/run_phase1_tests.py`，该入口隔离系统 keyring 并管理本项目测试临时目录。不要用测试失败输出检查真实凭据值。

开发基线使用 `python scripts/run_v2_action_baseline.py --config E:\path\to\config.yaml --model deepseek-chat --category repair --runs 2`，检查类改为 `--category inspect`。每批最多 2 Run／12 模型请求，按已有每 Run 限额执行；只运行冻结的开发合成样本，最终样本不接受选择。该驱动自动批准的动作有额外样本边界，细节见 `evals/v2/SPEC.md`，不能作为通用项目的自动批准配置。归档位于 `.harness/phase1-evals/<唯一批次>`，包含全部请求、响应、输出和独立检查；正式真实结果会另行版本化。

协议依据：[DeepSeek 工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。适配器使用非思考模式，保存原 assistant 工具调用信息，并按调用 ID 回传完整观测；不依赖 Beta strict 模式。


## 本地归档与只读查询

显式 `--archive-dir` 启用审计，参数为已经存在的项目外可信目录。每次 Run 创建新的 ID 子目录，不复用旧 Run；未指定时报告 `audit.status=DISABLED`，只有本次 stdout 报告，不声称已持久化。

```powershell
harness-v2 --project E:\path\to\project --task "读取 README" --model mock --archive-dir E:\path\to\audit
harness-v2 --inspect-archive E:\path\to\audit\实际run_id
```

查询入口仅接受 `--inspect-archive` 和路径，无需模型、配置或凭据，不读取项目、不执行工具，不恢复旧任务。完整性校验通过返回 0，不完整返回 1；不能与执行选项组合。可查询完整报告、事件及制品摘要，完整命令输出保存在该 Run 的 `artifact-<id>.txt`。格式、大小边界及异常记录语义见 [AUDIT.md](AUDIT.md)。

归档包含任务与限额、原始观测、审批和计费记录、缓存的有效决策，以及已准备的供应商请求／已收到的响应（已知凭据脱敏）。请求准备记录不等于实际发送；以模型账单中的尝试阶段和运行记录共同检查。派发前保存意图／许可，但快照完成之后动作可能已经开始，重启时不能根据 PREPARED 推断可以安全重发。

执行入口在模型／工具派发前、观测后、审批／暂停返回和控制轮询边界保存检查点。控制轮询避免重复写入不变快照；已注册命令制品仍重新核对来源内容。归档过程的耗时计入总运行限额，写完后再次检查派发截止。命令制品按本 Run 注册表核对完整哈希后复制到档案，不扫描旧制品或接受模型指定的来源路径。

归档失败阻止新动作；尚未发出的模型意图释放预留，已经取得的工具结果保留。在途执行需要按原协议收尾，不能把取消请求等同于已停止。最终归档失败不会篡改已达成的 Run 终态，但报告 `audit.status=FAILED`／`AUDIT_WRITE_FAILED` 且 CLI 返回 1，不能宣称完整可追溯。普通 CLI 未配置独立验收器时，正常结束的 Assessment 仍为 UNVERIFIED；UNKNOWN 为 INCONCLUSIVE。报告的 assessment_details 按条件区分模型声明、工具观测、独立验证及未决事项，具体判定与新鲜度边界见 AUDIT.md。

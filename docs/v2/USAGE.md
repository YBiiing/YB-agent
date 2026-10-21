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

默认工具集仅开放项目内受控 UTF-8 文件读取，单文件最多 16384 bytes；隐藏分段、敏感名称、绝对/父目录/ADS/设备/短名路径、链接和硬链接会被拒绝。这是面向可信受控项目的防护，不是操作系统沙箱，不保证对并发恶意文件系统安全。当前仅实际验证 Windows；Linux 未验证。任意名称中含 `~` 也会保守拒绝。

## 输出与限制

stdout 输出 JSON 报告，含 Run/Step/Decision/调用/观测/尝试/事件及模型用量。退出码 0 表示运行正常交付，1 表示未正常交付，2 表示配置或参数错误。`COMPLETED` 不等于目标验收 `PASSED`；当前 Assessment 保持 `UNVERIFIED`。完整持久审计、正式独立验收及 CLI 运行中的暂停/继续控制由后续小目标交付。

审批机制已接入启动边界：默认 `--approvals deny` 对需要人类批准的动作返回拒绝反馈；`--approvals interactive` 展示具体动作，输入 `yes` 批准、`cancel` 取消，其他输入（包括 EOF）拒绝。审批绑定当前 Run、主体、动作参数/版本、可信资源事实、策略版本和期限；资源变化或过期会重新申请，硬拒绝不能被批准覆盖。

默认 `--tools read`。显式 `--tools workspace --approvals interactive` 增加 `write_file(path, content, expected_sha256)`，模型必须提供读取时的内容 SHA-256，新文件使用 `MISSING`。只在已有目录内写入，内容为有界 UTF-8；敏感路径、链接、范围外路径仍拒绝。执行前与提交前重新核对版本，既有文件暂存后替换，新文件无覆盖发布。结果不明标记 `UNKNOWN` 并终止，不自动重试；线程超时不代表底层写入已经停止。

写入面向受控单写者工作区，哈希检查与替换不是抵御不合作外部写者的原子条件写入，也不保证崩溃后的持久恢复。当前读取授权事实使用路径及 stat 版本，写入使用真实内容哈希。完整 CLI 运行中控制后续交付。

## 受控 Python 检查（Windows）

显式 `--tools commands` 提供读取、版本写入和 `run_command(program, args)`。当前 program 只接受 `python`，固定映射本解释器；args 仅包含一个通过 `--command-script` 列入范围的相对 `.py` 路径。原始 Shell、任意可执行程序、解释器选项及脚本额外参数均未开放。

```powershell
harness-v2 --project E:\path\to\trusted-synthetic-project --task "先运行 check.py 观察失败，修复后再检查" --model deepseek-chat --config E:\path\to\config.yaml --tools commands --command-script check.py --command-input calculator.py --artifact-dir E:\path\to\v2-output --approvals interactive
```

每个命令都会重新审批，绑定脚本和显式 `--command-input` 文件的内容哈希（最多 64 个声明输入），启动时再次核对；脚本自动作为输入。必须自行声明间接依赖与数据文件，这不是自动完整依赖分析。制品目录必须在项目外，防止检查输出污染项目文件；输出以唯一文件名保存，不覆盖既有制品。

命令默认 5 秒，有界组合 stdout/stderr 最多 65536 bytes，超限终止进程树；保存完整的有界 UTF-8 输出（非法序列替换、已知凭据脱敏）及 SHA-256，模型反馈含最多 4096 字符的头尾预览、退出码、输入前后哈希和制品路径。达到硬上限的输出不宣称完整。非零退出表示检查发现问题或程序失败，工具的 `SUCCESS` 仅表示取得可靠执行观测，须查看 `exit_code`。

隔离 launcher 加入 Windows Job 后才启动项目脚本；Job 不开启 breakaway，限制 16 个活动进程和 256 MiB 内存。子进程环境不继承模型 API 凭据，启用 UTF-8 并禁写 bytecode。超时／取消后尝试停止整棵进程树并确认 Job 无活动成员、已采样进程句柄退出；未采样短命进程的内核对象仍可能稍后清理。清理等待共用两秒额度，OS 调用及调度另计。无法确认停止或执行后的证据保存失败会报告 `UNKNOWN` 并终止 Run；不自动重试。

停止确认不等于撤销副作用，反馈始终说明已启动命令可能产生副作用，非零退出同样如此。此能力只适用于可信受控代码；项目 cwd、输入声明、最小环境和 Job 都不能限制任意代码访问文件、网络或系统权限。当前仅验证 Windows，Linux 命令拒绝执行。监管依据为 [Microsoft Job Object API](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)。

离线回归统一使用 `python scripts/run_phase1_tests.py`，该入口隔离系统 keyring 并管理本项目测试临时目录。不要用测试失败输出检查真实凭据值。

开发基线使用 `python scripts/run_v2_action_baseline.py --config E:\path\to\config.yaml --model deepseek-chat --category repair --runs 2`，检查类改为 `--category inspect`。每批最多 2 Run／12 模型请求，按已有每 Run 限额执行；只运行冻结的开发合成样本，最终样本不接受选择。该驱动自动批准的动作有额外样本边界，细节见 `evals/v2/SPEC.md`，不能作为通用项目的自动批准配置。归档位于 `.harness/phase1-evals/<唯一批次>`，包含全部请求、响应、输出和独立检查；正式真实结果会另行版本化。

协议依据：[DeepSeek 工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。适配器使用非思考模式，保存原 assistant 工具调用信息，并按调用 ID 回传完整观测；不依赖 Beta strict 模式。

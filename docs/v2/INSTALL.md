# V2 安装与独立使用

V2 使用 `harness-v2`，旧版继续使用 `harness`。包的现有版本号仍为 0.1.1，本阶段没有创建新 Release、推送或发布。Python 声明最低 3.11；本轮实际环境为 Windows／Python 3.13，不能据此宣称所有 Python 版本与平台都完成验证。

## 从源码安装到新环境

以下为 Windows PowerShell，在仓库根运行；直接使用虚拟环境解释器，不要求修改 PowerShell 执行策略或激活脚本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\harness-v2.exe --help
.\.venv\Scripts\harness.exe --help
```

首次安装可能需要联网取得运行依赖和隔离构建依赖。普通用户不需要 dev extras；开发测试安装 `".[dev]"`。需要 editable 开发模式时改用 `-e .`。若使用 SOCKS 代理，安装 `".[proxy]"`，不要通过关闭代理或改变系统网络设置掩盖缺失依赖。

也可以先构建 wheel，再把 wheel 安装到另一环境：

```powershell
python -m pip wheel --no-deps --wheel-dir .harness\wheels .
# 用实际生成的 wheel 文件名替换下方名称。
.\.venv\Scripts\python.exe -m pip install .harness\wheels\harness-0.1.1-py3-none-any.whl
```

不要随意添加 `--no-build-isolation`；未预装 setuptools 的环境将无法导入构建后端。wheel 安装会按元数据取得运行依赖；仅 `--no-deps` 安装不能证明新环境具备可用运行时。源码包仍使用既有 `src` 包名，不要求位于仓库根才能导入；避免同一环境中安装其他占用该顶层名称的项目。

## 可直接运行的离线闭环

先在仓库外创建一个自己的空演示目录，并准备 `README.md`（普通 UTF-8 文本）及项目外审计目录。将下面三个占位路径改为实际路径；所有父目录必须存在。

```powershell
$projectPath = 'E:\path\to\demo-project'
$auditPath = 'E:\path\to\audit'
$v2Command = 'E:\path\to\YB-agent\.venv\Scripts\harness-v2.exe'
& $v2Command --project $projectPath --task '离线读取演示' --model mock --read-file README.md --archive-dir $auditPath
& $v2Command --inspect-archive 'E:\path\to\audit\从报告复制实际run_id'
```

mock 按脚本读取真实文件，不能证明自然语言任务能力。stdout 是最终 JSON；归档状态应为 FINALIZED，任务运行可以 COMPLETED，但没有独立验收器时 Assessment 仍 UNVERIFIED。相同命令还可由该虚拟环境的 `python -m src.v2` 运行。查询不读取凭据、不启动模型或工具，也不会继续旧 Run。

## 显式配置真实模型

在项目外维护配置文件，例如：

```yaml
llm:
  provider: deepseek
  model: deepseek-chat
  base_url: https://api.deepseek.com/v1
```

配置中不放 API key。可使用旧入口 `harness key set` 的隐藏输入保存到系统 keyring（service=harness／username=api_key）；V2 使用同一身份。已有环境凭据可由 `HARNESS_API_KEY` 提供，但不把值写入命令示例、项目文件、归档或 Git。V2 不自动加载 `.env`，不启动配置向导；未明确 `--model`／`--config` 时不会回退 mock。

```powershell
& $v2Command --project $projectPath --task '读取 README.md 并给出来源和结论' --model deepseek-chat --config 'E:\path\to\model.yaml' --archive-dir $auditPath --max-steps 2 --model-retries 0 --run-seconds 60
```

该冒烟任务最多两个模型决定、单次最多 1024 输出 tokens、60 秒总时限，仍受完整输入和累计 Token 限制。若模型没有在两个 Step 内形成最终回答，将明确 EXHAUSTED；不能无界重发直到成功。真实调用会计费。更长任务、审批、控制、写入、Windows 检查与制品按需读取见 [USAGE.md](USAGE.md)。

## 入口、退出码与兼容

| 项目 | V2 行为 |
| --- | --- |
| `harness` | 原 CLI／REPL／key／config／Web runtime，保留原配置语义 |
| `harness-v2`／`python -m src.v2` | 新单 Agent 核心，必须显式选模型；不继承旧配置的高预算 |
| 默认能力 | `--tools read`，需要审批的动作默认 deny |
| stdout／stderr | 最终 JSON／审批、控制状态和回执；可分别重定向 |
| 退出 0 | 执行 COMPLETED 且未发生审计错误；或只读查询完整性通过。不等于任务验收 PASSED |
| 退出 1 | FAILED／CANCELLED／EXHAUSTED、审计失败，或查询不完整记录 |
| 退出 2 | 参数或执行前配置／目录／模型设置错误，未开始有效任务 |
| 档案 | 显式 --archive-dir；不启用时 audit=DISABLED，不声称已持久化 |

当前实际支持声明限定于已验证 Windows 行为。Linux 命令拒绝执行；Linux 文件、控制和进程行为未验收，不能套用 Windows 结果。命令工具需要可信受控代码、显式脚本和输入声明，并仍需逐动作审批；项目路径限制和 Job Object 都不是任意 Python 的 OS 沙箱。异常进程退出只留下可查询记录，不自动续跑、重放、确认未知结果或清除残留进程。

## 排错

| 表现／安全错误码 | 检查方式 |
| --- | --- |
| 找不到 harness-v2 | 使用已安装环境的完整 Scripts 路径，或同一解释器执行 `-m src.v2`；确认没有误用其他 Python |
| 无法导入 setuptools.build_meta | 使用默认隔离构建安装，让 pip 在隔离环境准备后端；本项目不要求修改系统 Python |
| MODEL_CREDENTIAL_MISSING | 检查当前 OS 用户的 keyring 身份或当前进程凭据环境；不要打印凭据值排查 |
| MODEL_CONFIGURATION_ERROR | 核对 YAML provider／model／官方 HTTPS base_url，命令模型名必须一致 |
| MODEL_PROXY_DEPENDENCY_MISSING | 在同一虚拟环境安装 proxy extra |
| APPROVAL_UNAVAILABLE／DENIED | 默认 deny；有意授权写入才显式选 interactive 或 control-file，硬规则仍有效 |
| MODEL_INPUT_LIMIT／各预算上限 | 任务或必需上下文放不下，或额度已用尽；检查报告，不盲目重复有副作用的动作 |
| AUDIT_WRITE_FAILED | 检查项目外目录权限、空间和制品是否变化；档案可能不完整，报告不会声称完整追踪 |
| INCOMPLETE／UNFINISHED_OR_INTERRUPTED | 前者校验未通过，后者只表示已保存 OPEN 检查点；人工核对效果，不据此自动续跑 |

本机已实际完成 wheel→全新虚拟环境→仓库外 mock／归档查询／审批命令及两请求真实冒烟，完整环境、用量和两次验证准备事件见 [安装验证报告](../../evals/v2/results/install-smoke-v1/REPORT.md)；不是只验证 editable 源码导入。机制覆盖见 [CONTRACT_TESTS.md](CONTRACT_TESTS.md)，审计及新鲜度语义见 [AUDIT.md](AUDIT.md)；最终能力结论以固定评测和 G1 为准。

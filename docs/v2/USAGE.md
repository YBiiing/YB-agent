# V2 当前使用方式

当前已实现只读循环、离线 mock 和 DeepSeek 适配。真实能力基线在 P1-04c 验证；第一阶段其余能力按 PHASE1_PLAN.md 继续实施，不能将当前结果视为 G1 完成。

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

工具仅开放项目内受控 UTF-8 文件读取，默认单文件最多 16384 bytes；隐藏分段、敏感名称、绝对/父目录/ADS/设备/短名路径、链接和硬链接会被拒绝。这是面向可信受控项目的防护，不是操作系统沙箱，不保证对并发恶意文件系统安全。当前仅实际验证 Windows；Linux 未验证。任意名称中含 `~` 也会保守拒绝。

## 输出与限制

stdout 输出 JSON 报告，含 Run/Step/Decision/调用/观测/尝试/事件及模型用量。退出码 0 表示运行正常交付，1 表示未正常交付，2 表示配置或参数错误。`COMPLETED` 不等于目标验收 `PASSED`；当前 Assessment 保持 `UNVERIFIED`。完整持久审计、独立验收、写工具、命令及 CLI 实时审批/控制由后续小目标交付。

离线回归统一使用 `python scripts/run_phase1_tests.py`，该入口隔离系统 keyring 并管理本项目测试临时目录。不要用测试失败输出检查真实凭据值。

协议依据：[DeepSeek 工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。适配器使用非思考模式，保存原 assistant 工具调用信息，并按调用 ID 回传完整观测；不依赖 Beta strict 模式。

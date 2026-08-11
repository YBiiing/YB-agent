# Coding Agent Harness v0.1.1

`v0.1.1` 是面向真实 Windows 终端使用的兼容性补丁版本。

## 修复内容

- HITL 审批提示改用 ASCII 警告标记，避免 Windows GBK 控制台因 `⚠` 崩溃。
- CLI 输出对终端无法编码的 Unicode 字符进行安全降级。
- 审批输入遇到 EOF 或 Ctrl+C 时默认拒绝，避免中断导致崩溃或误执行。
- 模型连续 3 次返回无效 Action 时提前熔断，并在 Trace 中给出明确停止原因。
- REPL 将 parser error 标记为 `[ERROR]`，不再显示为 `[OK]`。
- 文档补充 PowerShell 中文管道输入和旧 editable 安装修复方式。
- 系统上下文显式声明运行平台，并要求文件读取优先使用 `read_file`，避免 Windows 上生成 Unix `cat/grep` 命令。

## Release 产物

- `harness-0.1.1-py3-none-any.whl`：Python wheel。
- `yb-agent-v0.1.1-docker-image.tar.gz`：已构建的 Docker 镜像归档。
- `SHA256SUMS.txt`：上述产物的 SHA256 校验值。

## 安装 wheel

```bash
python -m pip install harness-0.1.1-py3-none-any.whl
harness --help
```

## 加载 Docker 镜像

```bash
docker load -i yb-agent-v0.1.1-docker-image.tar.gz
docker run --rm yb-agent:v0.1.1 --help
```

运行时 API key 不包含在 wheel、Docker 镜像或 Release 附件中。

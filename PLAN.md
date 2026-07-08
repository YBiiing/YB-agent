# Coding Agent Harness 实现计划

> **给 agentic worker 的说明：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 来逐任务实现本计划。步骤使用 checkbox（`- [ ]`）语法追踪。

**目标：** 构建一个终端式 Coding Agent Harness，自己实现 agent 主循环、工具分发、护栏链、反馈闭环，全部机制可在 mock LLM 下做确定性单元测试。

**架构：** Pipeline 架构——上下文 → LLM → 解析 → 护栏 → 执行 → 反馈 → 循环。每个模块独立可测，mock LLM 替换真实 LLM。Python 3.11+，CLI/REPL 为主交互界面，最小 FastAPI WebUI 做演示。

**技术栈：** Python 3.11+, pytest, keyring, FastAPI + uvicorn, Docker, OpenAI 兼容 API

## 全局约束

- Python >= 3.11
- 所有核心机制必须能用 mock/stub LLM 做单元测试（单测不依赖真实 LLM 和网络）
- TDD：先写失败测试 → 确认红色 → 实现 → 确认绿色 → 提交
- 凭据禁止硬编码、禁止进入 Git 历史
- Docker 分发：`docker build && docker run` 可启动
- `.gitlab-ci.yml` 必须包含 `unit-test` job
- 包管理：`pip` + `pyproject.toml`
- 配置文件：项目根目录 `config.yaml`
- 记忆目录：`.harness/memory/`
- 基准验证环境：Python 3.11；本地可用 Python 3.11+，但 CI/Docker 以 Python 3.11 为准
- Windows fallback：若 `make` 不可用，用 `python -m pytest tests/unit/ -v` 替代 `make test`，用 `python -m pytest tests/demo/ -v` 替代 `make demo`
- 跨平台测试：不要依赖 `sleep`、`rm` 等 Unix-only 命令；需要超时时使用 `python -c "import time; time.sleep(10)"`

---

## 文件结构

```
src/
├── __init__.py
├── models.py              # 所有 dataclass：Action, ToolResult, GuardrailDecision, FeedbackSignal, Step, Trace, Message
├── loop.py                # AgentLoop：主循环 + 停机判断
├── actions.py             # ActionParser：LLM 文本 → Action
├── feedback.py            # FeedbackParser + TestSensor, LintSensor, ExitCodeSensor
├── memory.py              # Memory：会话内 + 项目级
├── config.py              # Config：加载/保存 config.yaml
├── llm/
│   ├── __init__.py
│   ├── base.py            # LLMClient 抽象类
│   ├── mock.py            # ScriptedMockLLM, RuleBasedMockLLM
│   └── openai.py          # OpenAIClient（OpenAI 兼容 API）
├── tools/
│   ├── __init__.py
│   ├── registry.py        # ToolRegistry：注册 + 分发
│   ├── files.py           # read_file, write_file 处理器
│   └── shell.py           # shell 处理器
├── guardrails/
│   ├── __init__.py
│   ├── chain.py           # GuardrailChain：顺序规则检查
│   ├── rules.py           # 内置规则：PathSandbox, DangerousCmd, NetworkGate, FileWriteGate, DestructiveOp
│   └── hitl.py            # HITLConsole：暂停 + 审批提示
├── cli/
│   ├── __init__.py
│   ├── main.py            # 入口：harness 命令
│   └── repl.py            # REPL 循环
└── web/
    ├── __init__.py
    ├── server.py          # FastAPI 应用
    └── templates/
        └── index.html     # 单页 Trace 查看器 + demo 按钮
tests/
├── conftest.py            # 共享 fixtures
├── unit/
│   ├── test_models.py
│   ├── test_loop.py
│   ├── test_actions.py
│   ├── test_tools.py
│   ├── test_guardrails.py
│   ├── test_feedback.py
│   ├── test_memory.py
│   └── test_mock_llm.py
└── demo/
    ├── demo_guardrail.py
    ├── demo_feedback_loop.py
    └── demo_focus_dimension.py
examples/
└── sample_project/        # 演示用最小项目：一个 .py 文件 + 一个测试
config.yaml
pyproject.toml
Makefile
Dockerfile
.gitlab-ci.yml
README.md
```

---

### 任务 1：项目骨架与配置 ✅ — `d4494ea`

**目标：** 建立可安装、可导入、可运行测试命令的最小 Python 项目骨架，为后续所有任务提供包结构、配置文件和示例项目。

**文件：**
- 创建：`pyproject.toml`
- 创建：`config.yaml`
- 创建：`Makefile`
- 创建：`src/__init__.py`
- 创建：`src/llm/__init__.py`
- 创建：`src/tools/__init__.py`
- 创建：`src/guardrails/__init__.py`
- 创建：`src/cli/__init__.py`
- 创建：`src/web/__init__.py`
- 创建：`tests/__init__.py`
- 创建：`tests/unit/__init__.py`
- 创建：`tests/demo/__init__.py`
- 创建：`tests/conftest.py`
- 创建：`examples/sample_project/calculator.py`
- 创建：`examples/sample_project/test_calculator.py`
- 创建：`.gitignore`

**接口：**
- 消费：无
- 产出：`config.yaml`（由任务 8 的 `src/config.py` 加载）、`pyproject.toml`（所有任务的依赖）、`Makefile`（test/lint/run/demo 命令）、示例项目（供 demo 任务使用）

- [ ] **步骤 1：创建 `pyproject.toml`**

```toml
[project]
name = "harness"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.0.0",
    "keyring>=24.0.0",
    "pyyaml>=6.0",
    "fastapi>=0.100.0",
    "uvicorn>=0.23.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
]

[project.scripts]
harness = "src.cli.main:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **步骤 2：创建 `config.yaml`**

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  base_url: https://api.openai.com/v1
  max_tokens: 4096

loop:
  max_steps: 20
  tool_timeout_sec: 60

guardrails:
  rules:
    path_sandbox: {enabled: true}
    dangerous_cmd: {enabled: true}
    network_gate: {enabled: true}
    file_write_gate: {enabled: true}
    destructive_op: {enabled: true}

tools:
  allowed_commands: ["pytest", "ruff", "mypy", "git", "ls", "cat", "grep", "find"]

memory:
  max_recent_steps: 5
  project_dir: .harness/memory
```

- [ ] **步骤 3：创建 `Makefile`**

```makefile
.PHONY: test lint demo run install

install:
	pip install -e .[dev]

test:
	pytest tests/unit/ -v

lint:
	ruff check src/ tests/

demo:
	pytest tests/demo/ -v

run:
	python -m src.cli.main
```

- [ ] **步骤 4：创建 `src/__init__.py`**（空文件）

- [ ] **步骤 5：创建所有 `__init__.py`**（空文件）：`src/llm/`、`src/tools/`、`src/guardrails/`、`src/cli/`、`src/web/`、`tests/`、`tests/unit/`、`tests/demo/`

- [ ] **步骤 6：创建 `tests/conftest.py`**

```python
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_project():
    """创建临时项目目录用于测试。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir()
        yield project_dir


@pytest.fixture
def sample_config():
    """返回最小配置字典用于测试。"""
    return {
        "llm": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "max_tokens": 4096,
        },
        "loop": {"max_steps": 20, "tool_timeout_sec": 60},
        "guardrails": {
            "rules": {
                "path_sandbox": {"enabled": True},
                "dangerous_cmd": {"enabled": True},
                "network_gate": {"enabled": True},
                "file_write_gate": {"enabled": True},
                "destructive_op": {"enabled": True},
            }
        },
        "tools": {
            "allowed_commands": ["pytest", "ruff", "mypy", "git", "ls", "cat", "grep", "find"]
        },
        "memory": {"max_recent_steps": 5, "project_dir": ".harness/memory"},
    }
```

- [ ] **步骤 7：创建 `examples/sample_project/calculator.py`**

```python
def add(a: int, b: int) -> int:
    return a + b


def subtract(a: int, b: int) -> int:
    # BUG: 应该是 a - b
    return a + b
```

- [ ] **步骤 8：创建 `examples/sample_project/test_calculator.py`**

```python
from calculator import add, subtract


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2  # 这个会失败，因为 subtract 有 bug
```

- [ ] **步骤 9：创建 `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.env
.harness/
dist/
*.egg-info/
.pytest_cache/
.ruff_cache/
```

- [ ] **步骤 10：安装依赖并验证**

运行：`pip install -e .[dev]`
预期：所有包安装成功，无错误

- [ ] **步骤 11：验证项目骨架可用**

运行：`python -c "import src; print('OK')"`
预期：`OK`

- [ ] **步骤 12：提交**

```bash
git add -A
git commit -m "feat: 项目骨架搭建——配置、Makefile、示例项目

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 2：核心数据模型 ✅ — `33eaf41`

**目标：** 实现所有核心数据对象，使后续 LLM、工具、护栏、反馈、记忆和主循环模块共享同一套类型契约。

**文件：**
- 创建：`src/models.py`
- 创建：`tests/unit/test_models.py`

**接口：**
- 消费：无
- 产出：`Action`、`ToolResult`、`GuardrailDecision`、`FeedbackSignal`、`Step`、`Trace`、`Message` dataclass（所有后续任务消费）

- [ ] **步骤 1：写失败测试 `tests/unit/test_models.py`**

```python
from src.models import (
    Action, ToolResult, GuardrailDecision,
    FeedbackSignal, Step, Trace, Message
)


def test_action_创建():
    action = Action(type="shell", params={"command": "pytest"}, raw='{"type": "shell", ...}')
    assert action.type == "shell"
    assert action.params == {"command": "pytest"}
    assert action.raw == '{"type": "shell", ...}'


def test_tool_result_成功():
    action = Action(type="shell", params={"command": "pytest"}, raw="")
    result = ToolResult(action=action, success=True, output="3 passed", error=None, duration_ms=100)
    assert result.success is True
    assert result.output == "3 passed"
    assert result.error is None


def test_tool_result_失败():
    action = Action(type="shell", params={"command": "pytest"}, raw="")
    result = ToolResult(action=action, success=False, output="", error="command not found", duration_ms=10)
    assert result.success is False
    assert result.error == "command not found"


def test_guardrail_decision_放行():
    decision = GuardrailDecision(allowed=True, reason="safe", rule_name="PathSandbox", requires_approval=False)
    assert decision.allowed is True
    assert decision.requires_approval is False


def test_guardrail_decision_拦截():
    decision = GuardrailDecision(allowed=False, reason="dangerous: rm -rf", rule_name="DangerousCmd", requires_approval=False)
    assert decision.allowed is False
    assert decision.rule_name == "DangerousCmd"


def test_guardrail_decision_需审批():
    decision = GuardrailDecision(allowed=True, reason="network: curl", rule_name="NetworkGate", requires_approval=True)
    assert decision.allowed is True
    assert decision.requires_approval is True


def test_feedback_signal():
    signal = FeedbackSignal(
        status="fail",
        summary="1 failed, 1 passed",
        details=[{"test": "test_add", "status": "FAILED", "message": "AssertionError: expected 2, got 3"}],
        suggested_action="fix"
    )
    assert signal.status == "fail"
    assert signal.suggested_action == "fix"
    assert len(signal.details) == 1


def test_step_创建():
    action = Action(type="shell", params={"command": "pytest"}, raw="")
    guardrail = GuardrailDecision(allowed=True, reason="safe", rule_name="", requires_approval=False)
    result = ToolResult(action=action, success=True, output="ok", error=None, duration_ms=10)
    feedback = FeedbackSignal(status="pass", summary="all passed", details=[], suggested_action=None)
    step = Step(index=0, action=action, guardrail=guardrail, result=result, feedback=feedback, timestamp=1000.0)
    assert step.index == 0
    assert step.result is not None
    assert step.feedback is not None


def test_step_被拦截时无执行结果():
    action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
    guardrail = GuardrailDecision(allowed=False, reason="dangerous", rule_name="DangerousCmd", requires_approval=False)
    step = Step(index=0, action=action, guardrail=guardrail, result=None, feedback=None, timestamp=1000.0)
    assert step.result is None
    assert step.guardrail.allowed is False


def test_trace_创建():
    trace = Trace(task="fix bug", steps=[], start_time=1000.0, end_time=None)
    assert trace.task == "fix bug"
    assert len(trace.steps) == 0
    assert trace.end_time is None


def test_message_创建():
    msg = Message(role="system", content="你是一个 coding agent")
    assert msg.role == "system"
    assert msg.content == "你是一个 coding agent"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_models.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'src.models'`

- [ ] **步骤 3：实现 `src/models.py`**

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    type: str
    params: dict[str, Any]
    raw: str


@dataclass
class ToolResult:
    action: Action
    success: bool
    output: str
    error: str | None
    duration_ms: int


@dataclass
class GuardrailDecision:
    allowed: bool
    reason: str
    rule_name: str
    requires_approval: bool


@dataclass
class FeedbackSignal:
    status: str                # "pass" | "fail" | "error"
    summary: str
    details: list[dict]
    suggested_action: str | None  # "fix" | "retry" | "investigate" | None


@dataclass
class Step:
    index: int
    action: Action
    guardrail: GuardrailDecision
    result: ToolResult | None
    feedback: FeedbackSignal | None
    timestamp: float


@dataclass
class Trace:
    task: str
    steps: list[Step]
    start_time: float
    end_time: float | None


@dataclass
class Message:
    role: str
    content: str
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_models.py -v`
预期：11 个测试全部 PASS

- [ ] **步骤 5：提交**

```bash
git add src/models.py tests/unit/test_models.py
git commit -m "feat: 核心数据模型——Action, ToolResult, GuardrailDecision 等

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 3：LLM 抽象层——基类 + Mock ✅ — `aa72df9`

**目标：** 定义可替换的 LLM 客户端接口，并实现两个确定性 mock LLM，保证核心机制可脱离真实网络和真实 LLM 测试。

**文件：**
- 创建：`src/llm/base.py`
- 创建：`src/llm/mock.py`
- 创建：`tests/unit/test_mock_llm.py`

**接口：**
- 消费：`src/models.py` 中的 `Action`、`Message`
- 产出：`LLMClient` 抽象类，`async chat(messages: list[Message]) -> str`；`ScriptedMockLLM`，`__init__(actions: list[Action])`；`RuleBasedMockLLM`，`__init__(rules: dict[str, Action])`

- [ ] **步骤 1：写失败测试 `tests/unit/test_mock_llm.py`**

```python
import pytest
from src.models import Action, Message
from src.llm.base import LLMClient
from src.llm.mock import ScriptedMockLLM, RuleBasedMockLLM


class TestLLMClient:
    """验证 LLMClient 是抽象类，不能直接实例化。"""

    def test_不能实例化抽象类(self):
        with pytest.raises(TypeError):
            LLMClient()


class TestScriptedMockLLM:
    @pytest.mark.asyncio
    async def test_按序列返回动作(self):
        actions = [
            Action(type="read_file", params={"path": "foo.py"}, raw=""),
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="stop", params={}, raw=""),
        ]
        mock = ScriptedMockLLM(actions)
        messages = [Message(role="user", content="fix the bug")]

        result1 = await mock.chat(messages)
        assert result1 == '{"type": "read_file", "params": {"path": "foo.py"}}'

        result2 = await mock.chat(messages)
        assert result2 == '{"type": "shell", "params": {"command": "pytest"}}'

        result3 = await mock.chat(messages)
        assert result3 == '{"type": "stop", "params": {}}'

    @pytest.mark.asyncio
    async def test_序列耗尽返回stop(self):
        actions = [Action(type="read_file", params={"path": "foo.py"}, raw="")]
        mock = ScriptedMockLLM(actions)
        messages = [Message(role="user", content="test")]

        await mock.chat(messages)  # 消耗唯一一个动作
        result = await mock.chat(messages)  # 已耗尽
        assert result == '{"type": "stop", "params": {}}'


class TestRuleBasedMockLLM:
    @pytest.mark.asyncio
    async def test_匹配关键词返回对应动作(self):
        rules = {
            "FAILED": Action(type="write_file", params={"path": "foo.py", "content": "fixed"}, raw=""),
            "PASSED": Action(type="stop", params={}, raw=""),
        }
        mock = RuleBasedMockLLM(rules)
        messages = [Message(role="user", content="FAILED: test_add - AssertionError")]

        result = await mock.chat(messages)
        assert result == '{"type": "write_file", "params": {"path": "foo.py", "content": "fixed"}}'

    @pytest.mark.asyncio
    async def test_无匹配返回stop(self):
        rules = {
            "FAILED": Action(type="write_file", params={"path": "foo.py", "content": "fixed"}, raw=""),
        }
        mock = RuleBasedMockLLM(rules)
        messages = [Message(role="user", content="一切正常")]

        result = await mock.chat(messages)
        assert result == '{"type": "stop", "params": {}}'

    @pytest.mark.asyncio
    async def test_首个匹配规则优先(self):
        rules = {
            "FAILED": Action(type="write_file", params={"path": "a.py", "content": "fix a"}, raw=""),
            "test_add": Action(type="write_file", params={"path": "b.py", "content": "fix b"}, raw=""),
        }
        mock = RuleBasedMockLLM(rules)
        messages = [Message(role="user", content="FAILED: test_add - something wrong")]

        result = await mock.chat(messages)
        # "FAILED" 在消息中最先出现，应先匹配
        assert "a.py" in result
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_mock_llm.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：实现 `src/llm/base.py`**

```python
from abc import ABC, abstractmethod
from src.models import Message


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message]) -> str:
        """发送消息给 LLM，返回文本响应。"""
        ...
```

- [ ] **步骤 4：实现 `src/llm/mock.py`**

```python
import json
from src.models import Action, Message
from src.llm.base import LLMClient


class ScriptedMockLLM(LLMClient):
    def __init__(self, actions: list[Action]):
        self._actions = actions
        self._index = 0

    async def chat(self, messages: list[Message]) -> str:
        if self._index >= len(self._actions):
            return '{"type": "stop", "params": {}}'
        action = self._actions[self._index]
        self._index += 1
        return json.dumps({"type": action.type, "params": action.params})


class RuleBasedMockLLM(LLMClient):
    def __init__(self, rules: dict[str, Action]):
        self._rules = rules

    async def chat(self, messages: list[Message]) -> str:
        combined = " ".join(m.content for m in messages)
        for keyword, action in self._rules.items():
            if keyword in combined:
                return json.dumps({"type": action.type, "params": action.params})
        return '{"type": "stop", "params": {}}'
```

- [ ] **步骤 5：运行测试确认通过**

运行：`pytest tests/unit/test_mock_llm.py -v`
预期：6 个测试 PASS

- [ ] **步骤 6：提交**

```bash
git add src/llm/base.py src/llm/mock.py tests/unit/test_mock_llm.py
git commit -m "feat: LLM 抽象层——LLMClient 基类 + ScriptedMockLLM + RuleBasedMockLLM

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 4：Action 解析器 ✅ — `ecdcbfe`

**目标：** 将 LLM 的文本输出解析成结构化 `Action`，并对未知工具、缺失参数和 JSON 错误给出可回灌的确定性错误。

**文件：**
- 创建：`src/actions.py`
- 创建：`tests/unit/test_actions.py`

**接口：**
- 消费：`src/models.py` 中的 `Action`
- 产出：`ActionParser` 类，`parse(text: str, known_tools: set[str]) -> Action`

- [ ] **步骤 1：写失败测试 `tests/unit/test_actions.py`**

```python
import pytest
from src.models import Action
from src.actions import ActionParser


class TestActionParser:
    def setup_method(self):
        self.parser = ActionParser()
        self.known_tools = {"read_file", "write_file", "shell", "stop"}

    def test_解析json代码块(self):
        text = '''我来运行测试。
```json
{"type": "shell", "params": {"command": "pytest"}}
```'''
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "shell"
        assert action.params == {"command": "pytest"}

    def test_解析无代码块的纯json(self):
        text = '{"type": "read_file", "params": {"path": "foo.py"}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "read_file"
        assert action.params == {"path": "foo.py"}

    def test_未知工具返回error动作(self):
        text = '{"type": "delete_database", "params": {}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "error"
        assert "unknown tool" in action.params["message"].lower()

    def test_非法json返回error动作(self):
        text = "not json at all {{{"
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "error"
        assert "parse" in action.params["message"].lower()

    def test_raw字段保留原始文本(self):
        text = '{"type": "stop", "params": {"summary": "done"}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.raw == text

    def test_解析stop动作(self):
        text = '{"type": "stop", "params": {"summary": "all tests pass"}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "stop"
        assert action.params["summary"] == "all tests pass"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_actions.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：实现 `src/actions.py`**

```python
import json
import re
from src.models import Action


class ActionParser:
    def parse(self, text: str, known_tools: set[str]) -> Action:
        # 1. 尝试从 ```json ... ``` 代码块中提取 JSON
        json_str = self._extract_json(text)

        # 2. 解析 JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return Action(
                type="error",
                params={"message": f"JSON 解析失败: {e}"},
                raw=text,
            )

        tool_type = data.get("type", "")
        params = data.get("params", {})

        # 3. 校验工具类型
        if tool_type not in known_tools and tool_type != "error":
            return Action(
                type="error",
                params={"message": f"未知工具: {tool_type}"},
                raw=text,
            )

        return Action(type=tool_type, params=params, raw=text)

    def _extract_json(self, text: str) -> str:
        # 优先匹配 ```json ... ``` 代码块
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        # 尝试 ``` ... ``` 无语言标记的代码块
        match = re.search(r"```\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        # 退回到整个文本
        return text.strip()
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_actions.py -v`
预期：6 个测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/actions.py tests/unit/test_actions.py
git commit -m "feat: ActionParser——JSON 提取 + 工具校验

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 5：工具注册表 + 文件工具 ✅ — `0c2fd1c`

**目标：** 实现工具注册/分发机制和受项目目录限制的文件读写工具，为主循环执行 action 提供基础能力。

**文件：**
- 创建：`src/tools/registry.py`
- 创建：`src/tools/files.py`
- 创建：`tests/unit/test_tools.py`

**接口：**
- 消费：`src/models.py` 中的 `Action`、`ToolResult`
- 产出：`ToolRegistry` 类，`register(name: str, handler, schema: dict)` 和 `dispatch(action: Action, project_dir: str) -> ToolResult`；`read_file` 和 `write_file` 处理器函数

- [ ] **步骤 1：写失败测试 `tests/unit/test_tools.py`**

```python
import pytest
from pathlib import Path
from src.models import Action, ToolResult
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()

    def test_注册并分发(self):
        def echo_handler(action: Action, project_dir: str) -> ToolResult:
            return ToolResult(
                action=action, success=True,
                output=f"echo: {action.params.get('msg', '')}",
                error=None, duration_ms=0,
            )

        self.registry.register("echo", echo_handler, {"msg": "str"})
        action = Action(type="echo", params={"msg": "hello"}, raw="")
        result = self.registry.dispatch(action, "/tmp")
        assert result.success is True
        assert result.output == "echo: hello"

    def test_分发未知工具(self):
        action = Action(type="nonexistent", params={}, raw="")
        result = self.registry.dispatch(action, "/tmp")
        assert result.success is False
        assert "unknown tool" in result.error.lower()

    def test_处理器异常被捕获(self):
        def failing_handler(action: Action, project_dir: str) -> ToolResult:
            raise RuntimeError("boom")

        self.registry.register("fail", failing_handler, {})
        action = Action(type="fail", params={}, raw="")
        result = self.registry.dispatch(action, "/tmp")
        assert result.success is False
        assert "boom" in result.error


class TestFileTools:
    def test_读文件(self, temp_project):
        filepath = temp_project / "test.txt"
        filepath.write_text("hello world")
        action = Action(type="read_file", params={"path": str(filepath)}, raw="")
        result = read_file(action, str(temp_project))
        assert result.success is True
        assert result.output == "hello world"

    def test_读不存在的文件(self, temp_project):
        action = Action(type="read_file", params={"path": str(temp_project / "nonexistent.txt")}, raw="")
        result = read_file(action, str(temp_project))
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_读项目外文件被拒绝(self, temp_project):
        action = Action(type="read_file", params={"path": "/etc/passwd"}, raw="")
        result = read_file(action, str(temp_project))
        assert result.success is False
        assert "outside" in result.error.lower()

    def test_写文件(self, temp_project):
        action = Action(type="write_file", params={"path": str(temp_project / "out.txt"), "content": "new content"}, raw="")
        result = write_file(action, str(temp_project))
        assert result.success is True
        assert (temp_project / "out.txt").read_text() == "new content"

    def test_写文件自动创建父目录(self, temp_project):
        action = Action(type="write_file", params={"path": str(temp_project / "subdir" / "out.txt"), "content": "nested"}, raw="")
        result = write_file(action, str(temp_project))
        assert result.success is True
        assert (temp_project / "subdir" / "out.txt").read_text() == "nested"

    def test_写项目外文件被拒绝(self, temp_project):
        action = Action(type="write_file", params={"path": "/etc/hacked", "content": "bad"}, raw="")
        result = write_file(action, str(temp_project))
        assert result.success is False
        assert "outside" in result.error.lower()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_tools.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：实现 `src/tools/registry.py`**

```python
from typing import Any, Callable
from src.models import Action, ToolResult


Handler = Callable[[Action, str], ToolResult]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[Handler, dict]] = {}

    def register(self, name: str, handler: Handler, schema: dict) -> None:
        self._tools[name] = (handler, schema)

    def dispatch(self, action: Action, project_dir: str) -> ToolResult:
        if action.type not in self._tools:
            return ToolResult(
                action=action,
                success=False,
                output="",
                error=f"未知工具: {action.type}",
                duration_ms=0,
            )
        handler, _ = self._tools[action.type]
        try:
            return handler(action, project_dir)
        except Exception as e:
            return ToolResult(
                action=action,
                success=False,
                output="",
                error=str(e),
                duration_ms=0,
            )

    def tool_names(self) -> set[str]:
        return set(self._tools.keys())
```

- [ ] **步骤 4：实现 `src/tools/files.py`**

```python
from pathlib import Path
from src.models import Action, ToolResult


def _is_inside_project(path: str, project_dir: str) -> bool:
    """检查路径是否在项目目录内。"""
    try:
        resolved = Path(path).resolve()
        project_root = Path(project_dir).resolve()
        return str(resolved).startswith(str(project_root))
    except Exception:
        return False


def read_file(action: Action, project_dir: str) -> ToolResult:
    path = action.params.get("path", "")
    if not _is_inside_project(path, project_dir):
        return ToolResult(
            action=action, success=False, output="",
            error=f"路径在项目目录外: {path}", duration_ms=0,
        )
    filepath = Path(path)
    if not filepath.exists():
        return ToolResult(
            action=action, success=False, output="",
            error=f"文件不存在: {path}", duration_ms=0,
        )
    try:
        content = filepath.read_text(encoding="utf-8")
        return ToolResult(
            action=action, success=True, output=content,
            error=None, duration_ms=0,
        )
    except Exception as e:
        return ToolResult(
            action=action, success=False, output="",
            error=str(e), duration_ms=0,
        )


def write_file(action: Action, project_dir: str) -> ToolResult:
    path = action.params.get("path", "")
    content = action.params.get("content", "")
    if not _is_inside_project(path, project_dir):
        return ToolResult(
            action=action, success=False, output="",
            error=f"路径在项目目录外: {path}", duration_ms=0,
        )
    try:
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        return ToolResult(
            action=action, success=True, output="written",
            error=None, duration_ms=0,
        )
    except Exception as e:
        return ToolResult(
            action=action, success=False, output="",
            error=str(e), duration_ms=0,
        )
```

- [ ] **步骤 5：运行测试确认通过**

运行：`pytest tests/unit/test_tools.py -v`
预期：9 个测试 PASS

- [ ] **步骤 6：提交**

```bash
git add src/tools/registry.py src/tools/files.py tests/unit/test_tools.py
git commit -m "feat: ToolRegistry + 文件工具——read_file, write_file

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 6：Shell 工具

**目标：** 实现带工作目录、超时、stdout/stderr 捕获和耗时记录的 shell 工具，使测试、lint、git 等命令可被统一执行。

**文件：**
- 创建：`src/tools/shell.py`
- 修改：`tests/unit/test_tools.py`（追加 shell 测试）

**接口：**
- 消费：`src/models.py` 中的 `Action`、`ToolResult`；`src/tools/registry.py` 中的 `ToolRegistry`
- 产出：`shell_handler(action: Action, project_dir: str) -> ToolResult`

- [ ] **步骤 1：在 `tests/unit/test_tools.py` 末尾追加失败测试**

```python
import time
from src.tools.shell import shell_handler


class TestShellTool:
    def test_shell_成功执行(self, temp_project):
        action = Action(type="shell", params={"command": "echo hello"}, raw="")
        result = shell_handler(action, str(temp_project))
        assert result.success is True
        assert "hello" in result.output

    def test_shell_命令失败(self, temp_project):
        action = Action(type="shell", params={"command": "nonexistent_command_xyz"}, raw="")
        result = shell_handler(action, str(temp_project))
        assert result.success is False
        assert result.error is not None

    def test_shell_超时(self, temp_project):
        action = Action(type="shell", params={"command": "python -c \"import time; time.sleep(10)\""}, raw="")
        # 测试用短超时
        result = shell_handler(action, str(temp_project), timeout_sec=1)
        assert result.success is False
        assert "timeout" in result.error.lower()

    def test_shell_记录执行耗时(self, temp_project):
        action = Action(type="shell", params={"command": "echo test"}, raw="")
        result = shell_handler(action, str(temp_project))
        assert result.duration_ms > 0
```

- [ ] **步骤 2：运行测试确认 shell 部分失败**

运行：`pytest tests/unit/test_tools.py::TestShellTool -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：实现 `src/tools/shell.py`**

```python
import subprocess
import time
from src.models import Action, ToolResult


def shell_handler(action: Action, project_dir: str, timeout_sec: int = 60) -> ToolResult:
    command = action.params.get("command", "")
    start = time.time()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=project_dir,
        )
        duration_ms = int((time.time() - start) * 1000)
        success = result.returncode == 0
        return ToolResult(
            action=action,
            success=success,
            output=result.stdout,
            error=result.stderr if not success else None,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        return ToolResult(
            action=action,
            success=False,
            output="",
            error=f"命令超时 ({timeout_sec}s): {command}",
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return ToolResult(
            action=action,
            success=False,
            output="",
            error=str(e),
            duration_ms=duration_ms,
        )
```

- [ ] **步骤 4：运行全部工具测试确认通过**

运行：`pytest tests/unit/test_tools.py -v`
预期：13 个测试 PASS（9 原有 + 4 新增）

- [ ] **步骤 5：提交**

```bash
git add src/tools/shell.py tests/unit/test_tools.py
git commit -m "feat: Shell 工具——带超时的命令执行

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 7：护栏规则

**目标：** 实现内置护栏规则，明确直接拦截、需人工审批和安全放行三类判定。

**文件：**
- 创建：`src/guardrails/rules.py`
- 创建：`tests/unit/test_guardrails.py`

**接口：**
- 消费：`src/models.py` 中的 `Action`、`GuardrailDecision`
- 产出：`PathSandbox`、`DangerousCmd`、`NetworkGate`、`FileWriteGate`、`DestructiveOp` 规则类，每个有 `check(action: Action, project_dir: str) -> GuardrailDecision` 方法

- [ ] **步骤 1：写失败测试 `tests/unit/test_guardrails.py`**

```python
import pytest
from pathlib import Path
from src.models import Action, GuardrailDecision
from src.guardrails.rules import (
    PathSandbox, DangerousCmd, NetworkGate,
    FileWriteGate, DestructiveOp,
)


class TestPathSandbox:
    def test_放行项目内路径(self, temp_project):
        rule = PathSandbox()
        action = Action(type="read_file", params={"path": str(temp_project / "foo.py")}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True

    def test_拦截路径遍历(self, temp_project):
        rule = PathSandbox()
        action = Action(type="read_file", params={"path": "../etc/passwd"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False
        assert "outside" in decision.reason.lower()

    def test_拦截项目外绝对路径(self, temp_project):
        rule = PathSandbox()
        action = Action(type="write_file", params={"path": "/etc/hacked"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False

    def test_放行无路径的shell动作(self, temp_project):
        rule = PathSandbox()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True


class TestDangerousCmd:
    def test_拦截rm_rf(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False
        assert "rm" in decision.reason.lower()

    def test_拦截fork炸弹(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="shell", params={"command": ":(){ :|:& };:"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False

    def test_放行安全命令(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True

    def test_忽略非shell动作(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="read_file", params={"path": "rm -rf"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True


class TestNetworkGate:
    def test_标记curl需审批(self, temp_project):
        rule = NetworkGate()
        action = Action(type="shell", params={"command": "curl http://example.com"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_标记wget需审批(self, temp_project):
        rule = NetworkGate()
        action = Action(type="shell", params={"command": "wget http://example.com"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_放行pytest(self, temp_project):
        rule = NetworkGate()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False


class TestFileWriteGate:
    def test_覆盖已有文件需审批(self, temp_project):
        (temp_project / "exists.py").write_text("original")
        rule = FileWriteGate()
        action = Action(type="write_file", params={"path": str(temp_project / "exists.py"), "content": "new"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_新建文件放行(self, temp_project):
        rule = FileWriteGate()
        action = Action(type="write_file", params={"path": str(temp_project / "new.py"), "content": "new"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False

    def test_忽略非写入动作(self, temp_project):
        rule = FileWriteGate()
        action = Action(type="read_file", params={"path": "exists.py"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False


class TestDestructiveOp:
    def test_标记rm需审批(self, temp_project):
        rule = DestructiveOp()
        action = Action(type="shell", params={"command": "rm file.txt"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_标记mv需审批(self, temp_project):
        rule = DestructiveOp()
        action = Action(type="shell", params={"command": "mv a.py b.py"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_放行pytest(self, temp_project):
        rule = DestructiveOp()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_guardrails.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：实现 `src/guardrails/rules.py`**

```python
import re
from pathlib import Path
from src.models import Action, GuardrailDecision


class PathSandbox:
    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type not in ("read_file", "write_file"):
            return GuardrailDecision(allowed=True, reason="", rule_name="PathSandbox", requires_approval=False)
        path = action.params.get("path", "")
        if ".." in path:
            return GuardrailDecision(
                allowed=False,
                reason=f"检测到路径遍历: {path}",
                rule_name="PathSandbox",
                requires_approval=False,
            )
        try:
            resolved = Path(path).resolve()
            project_root = Path(project_dir).resolve()
            if not str(resolved).startswith(str(project_root)):
                return GuardrailDecision(
                    allowed=False,
                    reason=f"路径在项目目录外: {path}",
                    rule_name="PathSandbox",
                    requires_approval=False,
                )
        except Exception:
            return GuardrailDecision(
                allowed=False,
                reason=f"无效路径: {path}",
                rule_name="PathSandbox",
                requires_approval=False,
            )
        return GuardrailDecision(allowed=True, reason="", rule_name="PathSandbox", requires_approval=False)


class DangerousCmd:
    PATTERNS = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+/\*",
        r"rm\s+-rf\s+~",
        r":\(\)\s*\{\s*:\|\:&\s*\}\s*;",  # fork bomb
        r"mkfs",
        r"dd\s+if=",
        r"dropdb",
        r">\s*/dev/",
    ]

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "shell":
            return GuardrailDecision(allowed=True, reason="", rule_name="DangerousCmd", requires_approval=False)
        command = action.params.get("command", "")
        for pattern in self.PATTERNS:
            if re.search(pattern, command):
                return GuardrailDecision(
                    allowed=False,
                    reason=f"检测到危险命令: {command}",
                    rule_name="DangerousCmd",
                    requires_approval=False,
                )
        return GuardrailDecision(allowed=True, reason="", rule_name="DangerousCmd", requires_approval=False)


class NetworkGate:
    PATTERNS = [r"\bcurl\b", r"\bwget\b", r"\bnc\b", r"\bnetcat\b"]

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "shell":
            return GuardrailDecision(allowed=True, reason="", rule_name="NetworkGate", requires_approval=False)
        command = action.params.get("command", "")
        for pattern in self.PATTERNS:
            if re.search(pattern, command):
                return GuardrailDecision(
                    allowed=True,
                    reason=f"网络访问请求: {command}",
                    rule_name="NetworkGate",
                    requires_approval=True,
                )
        return GuardrailDecision(allowed=True, reason="", rule_name="NetworkGate", requires_approval=False)


class FileWriteGate:
    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "write_file":
            return GuardrailDecision(allowed=True, reason="", rule_name="FileWriteGate", requires_approval=False)
        path = action.params.get("path", "")
        if Path(path).exists():
            return GuardrailDecision(
                allowed=True,
                reason=f"覆盖已有文件: {path}",
                rule_name="FileWriteGate",
                requires_approval=True,
            )
        return GuardrailDecision(allowed=True, reason="", rule_name="FileWriteGate", requires_approval=False)


class DestructiveOp:
    PATTERNS = [r"\brm\b", r"\bmv\b", r"\bdel\b", r"\brmdir\b"]

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "shell":
            return GuardrailDecision(allowed=True, reason="", rule_name="DestructiveOp", requires_approval=False)
        command = action.params.get("command", "")
        for pattern in self.PATTERNS:
            if re.search(pattern, command):
                return GuardrailDecision(
                    allowed=True,
                    reason=f"可能的破坏性操作: {command}",
                    rule_name="DestructiveOp",
                    requires_approval=True,
                )
        return GuardrailDecision(allowed=True, reason="", rule_name="DestructiveOp", requires_approval=False)
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_guardrails.py -v`
预期：17 个测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/guardrails/rules.py tests/unit/test_guardrails.py
git commit -m "feat: 护栏规则——PathSandbox, DangerousCmd, NetworkGate, FileWriteGate, DestructiveOp

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 8：护栏链 + 配置加载器

**目标：** 实现按顺序执行的护栏链和 YAML 配置加载器，让规则启停与默认运行参数由 `config.yaml` 控制。

**文件：**
- 创建：`src/guardrails/chain.py`
- 创建：`src/config.py`
- 修改：`tests/unit/test_guardrails.py`（追加链测试）
- 创建：`tests/unit/test_config.py`

**接口：**
- 消费：`src/models.py` 中的 `Action`、`GuardrailDecision`；`src/guardrails/rules.py` 中的规则类
- 产出：`GuardrailChain` 类，`check(action: Action, project_dir: str) -> GuardrailDecision`；`Config` 类，`load(path: str) -> dict`

- [ ] **步骤 1：在 `tests/unit/test_guardrails.py` 末尾追加链测试**

```python
from src.guardrails.chain import GuardrailChain


class TestGuardrailChain:
    def test_首个规则拦截即停止后续(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(PathSandbox())
        chain.add_rule(DangerousCmd())
        action = Action(type="write_file", params={"path": "../etc/passwd"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is False
        assert decision.rule_name == "PathSandbox"

    def test_全部规则通过则放行(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(PathSandbox())
        chain.add_rule(DangerousCmd())
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_需审批信号透传(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(DangerousCmd())  # 通过
        chain.add_rule(DestructiveOp())  # 需审批
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is True
        assert decision.requires_approval is True
        assert decision.rule_name == "DestructiveOp"

    def test_拦截优先于审批(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(DangerousCmd())  # 拦截
        chain.add_rule(DestructiveOp())  # 本应审批
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is False
        assert decision.rule_name == "DangerousCmd"

    def test_禁用规则被跳过(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(DangerousCmd(), enabled=False)
        chain.add_rule(PathSandbox())
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = chain.check(action, str(temp_project))
        # DangerousCmd 被禁用，PathSandbox 对 shell 动作放行
        assert decision.allowed is True
        assert decision.rule_name == "PathSandbox"

    def test_空链全部放行(self, temp_project):
        chain = GuardrailChain()
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is True
```

- [ ] **步骤 2：写失败测试 `tests/unit/test_config.py`**

```python
import tempfile
from src.config import Config


class TestConfig:
    def test_加载yaml配置(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
loop:
  max_steps: 10
  tool_timeout_sec: 30
guardrails:
  rules:
    path_sandbox: {enabled: false}
    dangerous_cmd: {enabled: true}
""")
            f.flush()
            config = Config.load(f.name)
        assert config["loop"]["max_steps"] == 10
        assert config["guardrails"]["rules"]["path_sandbox"]["enabled"] is False

    def test_默认值(self):
        config = Config.defaults()
        assert config["loop"]["max_steps"] == 20
        assert config["guardrails"]["rules"]["dangerous_cmd"]["enabled"] is True
        assert "pytest" in config["tools"]["allowed_commands"]
```

- [ ] **步骤 3：运行测试确认失败**

运行：`pytest tests/unit/test_guardrails.py::TestGuardrailChain tests/unit/test_config.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 4：实现 `src/guardrails/chain.py`**

```python
from src.models import Action, GuardrailDecision


class GuardrailChain:
    def __init__(self):
        self._rules: list[tuple[object, bool]] = []

    def add_rule(self, rule, enabled: bool = True) -> None:
        self._rules.append((rule, enabled))

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        for rule, enabled in self._rules:
            if not enabled:
                continue
            decision = rule.check(action, project_dir)
            if not decision.allowed:
                return decision  # 被拦截——立即停止链
            if decision.requires_approval:
                return decision  # 需审批——停止链，交给 HITL 处理
        return GuardrailDecision(
            allowed=True, reason="", rule_name="", requires_approval=False
        )
```

- [ ] **步骤 5：实现 `src/config.py`**

```python
import yaml
from pathlib import Path


class Config:
    @staticmethod
    def defaults() -> dict:
        return {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
                "max_tokens": 4096,
            },
            "loop": {"max_steps": 20, "tool_timeout_sec": 60},
            "guardrails": {
                "rules": {
                    "path_sandbox": {"enabled": True},
                    "dangerous_cmd": {"enabled": True},
                    "network_gate": {"enabled": True},
                    "file_write_gate": {"enabled": True},
                    "destructive_op": {"enabled": True},
                }
            },
            "tools": {
                "allowed_commands": [
                    "pytest", "ruff", "mypy", "git", "ls", "cat", "grep", "find"
                ]
            },
            "memory": {"max_recent_steps": 5, "project_dir": ".harness/memory"},
        }

    @staticmethod
    def load(path: str) -> dict:
        config = Config.defaults()
        filepath = Path(path)
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            _deep_merge(config, user_config)
        return config


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
```

- [ ] **步骤 6：运行测试确认通过**

运行：`pytest tests/unit/test_guardrails.py tests/unit/test_config.py -v`
预期：全部测试 PASS

- [ ] **步骤 7：提交**

```bash
git add src/guardrails/chain.py src/config.py tests/unit/test_guardrails.py tests/unit/test_config.py
git commit -m "feat: GuardrailChain + Config 配置加载器（YAML 支持）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 9：反馈解析器

**目标：** 将工具结果解析为结构化反馈信号，使测试失败、lint 错误和普通退出码都能被主循环回灌给 LLM。

**文件：**
- 创建：`src/feedback.py`
- 创建：`tests/unit/test_feedback.py`

**接口：**
- 消费：`src/models.py` 中的 `ToolResult`、`FeedbackSignal`
- 产出：`FeedbackParser` 类，`parse(result: ToolResult) -> FeedbackSignal`

- [ ] **步骤 1：写失败测试 `tests/unit/test_feedback.py`**

```python
import pytest
from src.models import Action, ToolResult, FeedbackSignal
from src.feedback import FeedbackParser


class TestFeedbackParser:
    def setup_method(self):
        self.parser = FeedbackParser()

    def test_解析pytest失败输出(self):
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="""
============================= test session starts =============================
tests/test_calc.py::test_add PASSED
tests/test_calc.py::test_sub FAILED

=========================== 1 failed, 1 passed in 0.5s ===========================
""",
            error=None,
            duration_ms=500,
        )
        signal = self.parser.parse(result)
        assert signal.status == "fail"
        assert signal.suggested_action == "fix"
        assert len(signal.details) == 1
        assert signal.details[0]["test"] == "tests/test_calc.py::test_sub"
        assert signal.details[0]["status"] == "FAILED"

    def test_解析pytest全部通过(self):
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="2 passed in 0.3s",
            error=None,
            duration_ms=300,
        )
        signal = self.parser.parse(result)
        assert signal.status == "pass"
        assert signal.suggested_action is None

    def test_解析lint输出(self):
        action = Action(type="shell", params={"command": "ruff check ."}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="src/foo.py:10:5: F841 Local variable `x` is assigned to but never used",
            error=None,
            duration_ms=100,
        )
        signal = self.parser.parse(result)
        assert signal.status == "fail"
        assert signal.suggested_action == "fix"
        assert len(signal.details) == 1
        assert signal.details[0]["file"] == "src/foo.py"
        assert signal.details[0]["line"] == "10"

    def test_解析退出码成功(self):
        action = Action(type="shell", params={"command": "echo hello"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="hello",
            error=None,
            duration_ms=10,
        )
        signal = self.parser.parse(result)
        assert signal.status == "pass"

    def test_解析退出码错误(self):
        action = Action(type="shell", params={"command": "bad_cmd"}, raw="")
        result = ToolResult(
            action=action,
            success=False,
            output="",
            error="command not found: bad_cmd",
            duration_ms=5,
        )
        signal = self.parser.parse(result)
        assert signal.status == "error"
        assert signal.suggested_action == "investigate"

    def test_解析非命令结果(self):
        action = Action(type="read_file", params={"path": "foo.py"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="def foo(): pass",
            error=None,
            duration_ms=1,
        )
        signal = self.parser.parse(result)
        assert signal.status == "pass"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_feedback.py -v`
预期：FAIL

- [ ] **步骤 3：实现 `src/feedback.py`**

```python
import re
from src.models import Action, ToolResult, FeedbackSignal


class FeedbackParser:
    def parse(self, result: ToolResult) -> FeedbackSignal:
        command = result.action.params.get("command", "")

        # 路由到 TestSensor
        if "pytest" in command or "====" in result.output:
            return self._parse_test(result)

        # 路由到 LintSensor
        if any(tool in command for tool in ("ruff", "mypy")) or re.search(r":\d+:\d+:", result.output):
            return self._parse_lint(result)

        # 默认：ExitCodeSensor
        return self._parse_exit_code(result)

    def _parse_test(self, result: ToolResult) -> FeedbackSignal:
        details = []
        for line in result.output.split("\n"):
            if "FAILED" in line and "::" in line:
                parts = line.split()
                test_name = parts[0] if parts else line.strip()
                message = ""
                details.append({"test": test_name, "status": "FAILED", "message": message})

        if details:
            return FeedbackSignal(
                status="fail",
                summary=f"{len(details)} 个测试失败",
                details=details,
                suggested_action="fix",
            )
        return FeedbackSignal(
            status="pass",
            summary="全部测试通过",
            details=[],
            suggested_action=None,
        )

    def _parse_lint(self, result: ToolResult) -> FeedbackSignal:
        details = []
        for line in result.output.strip().split("\n"):
            match = re.match(r"(.+?):(\d+):(\d+):\s*(\S+)\s*(.*)", line)
            if match:
                details.append({
                    "file": match.group(1),
                    "line": match.group(2),
                    "col": match.group(3),
                    "code": match.group(4),
                    "message": match.group(5).strip(),
                })

        if details:
            return FeedbackSignal(
                status="fail",
                summary=f"{len(details)} 个 lint 问题",
                details=details,
                suggested_action="fix",
            )
        return FeedbackSignal(
            status="pass",
            summary="无 lint 问题",
            details=[],
            suggested_action=None,
        )

    def _parse_exit_code(self, result: ToolResult) -> FeedbackSignal:
        if result.success:
            return FeedbackSignal(
                status="pass",
                summary="命令执行成功",
                details=[],
                suggested_action=None,
            )
        return FeedbackSignal(
            status="error",
            summary=f"命令执行失败: {result.error or '未知错误'}",
            details=[],
            suggested_action="investigate",
        )
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_feedback.py -v`
预期：6 个测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/feedback.py tests/unit/test_feedback.py
git commit -m "feat: FeedbackParser——TestSensor, LintSensor, ExitCodeSensor

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 10：记忆系统

**目标：** 实现会话内 Trace 摘要和项目级文本记忆，支持最近步骤注入与简单关键词检索。

**文件：**
- 创建：`src/memory.py`
- 创建：`tests/unit/test_memory.py`

**接口：**
- 消费：`src/models.py` 中的 `Step`、`Trace`
- 产出：`Memory` 类，`add_step(step)`、`get_recent_steps(n) -> list[Step]`、`write_convention(key, content)`、`get_convention(key) -> str|None`、`search(query) -> list[str]`

- [ ] **步骤 1：写失败测试 `tests/unit/test_memory.py`**

```python
import pytest
from pathlib import Path
from src.models import Action, ToolResult, GuardrailDecision, FeedbackSignal, Step
from src.memory import Memory


class TestMemory:
    def setup_method(self):
        self.memory = Memory(max_recent_steps=3)

    def test_添加并获取最近步骤(self):
        step1 = Step(
            index=0,
            action=Action(type="shell", params={"command": "pytest"}, raw=""),
            guardrail=GuardrailDecision(allowed=True, reason="", rule_name="", requires_approval=False),
            result=ToolResult(action=Action(type="shell", params={"command": "pytest"}, raw=""), success=True, output="1 failed", error=None, duration_ms=100),
            feedback=FeedbackSignal(status="fail", summary="1 failed", details=[], suggested_action="fix"),
            timestamp=1000.0,
        )
        self.memory.add_step(step1)
        recent = self.memory.get_recent_steps(3)
        assert len(recent) == 1
        assert recent[0].index == 0

    def test_最近步骤数量限制(self):
        for i in range(5):
            step = Step(
                index=i,
                action=Action(type="shell", params={"command": "pytest"}, raw=""),
                guardrail=GuardrailDecision(allowed=True, reason="", rule_name="", requires_approval=False),
                result=None,
                feedback=None,
                timestamp=float(i),
            )
            self.memory.add_step(step)
        recent = self.memory.get_recent_steps(3)
        assert len(recent) == 3
        assert recent[0].index == 2  # 保留的最旧一条
        assert recent[-1].index == 4  # 最新一条

    def test_项目记忆写入和读取(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory = Memory(project_dir=str(memory_dir))

        memory.write_convention("naming", "所有函数使用 snake_case 命名")
        result = memory.get_convention("naming")
        assert result == "所有函数使用 snake_case 命名"

    def test_项目记忆搜索(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory = Memory(project_dir=str(memory_dir))

        memory.write_convention("naming", "使用 snake_case")
        memory.write_convention("testing", "使用 pytest 和 fixtures")

        results = memory.search("pytest")
        assert len(results) >= 1
        assert any("pytest" in r for r in results)

    def test_标记已修改文件(self):
        self.memory.mark_file_modified("foo.py")
        self.memory.mark_file_modified("bar.py")
        assert self.memory.is_file_modified("foo.py") is True
        assert self.memory.is_file_modified("baz.py") is False

    def test_失败计数(self):
        assert self.memory.failure_count == 0
        self.memory.increment_failure()
        self.memory.increment_failure()
        assert self.memory.failure_count == 2
        self.memory.reset_failure_count()
        assert self.memory.failure_count == 0
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_memory.py -v`
预期：FAIL

- [ ] **步骤 3：实现 `src/memory.py`**

```python
from pathlib import Path
from src.models import Step


class Memory:
    def __init__(self, max_recent_steps: int = 5, project_dir: str = ".harness/memory"):
        self._steps: list[Step] = []
        self._max_recent_steps = max_recent_steps
        self._project_dir = Path(project_dir)
        self._modified_files: set[str] = set()
        self._failure_count = 0

    # ── 会话内记忆 ──

    def add_step(self, step: Step) -> None:
        self._steps.append(step)
        if len(self._steps) > self._max_recent_steps:
            self._steps = self._steps[-self._max_recent_steps:]

    def get_recent_steps(self, n: int | None = None) -> list[Step]:
        if n is None:
            n = self._max_recent_steps
        return self._steps[-n:]

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def increment_failure(self) -> None:
        self._failure_count += 1

    def reset_failure_count(self) -> None:
        self._failure_count = 0

    def mark_file_modified(self, filepath: str) -> None:
        self._modified_files.add(filepath)

    def is_file_modified(self, filepath: str) -> bool:
        return filepath in self._modified_files

    # ── 项目级记忆 ──

    def write_convention(self, key: str, content: str) -> None:
        self._project_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._project_dir / f"{key}.md"
        filepath.write_text(content, encoding="utf-8")

    def get_convention(self, key: str) -> str | None:
        filepath = self._project_dir / f"{key}.md"
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def search(self, query: str) -> list[str]:
        results = []
        if self._project_dir.exists():
            for filepath in self._project_dir.rglob("*.md"):
                content = filepath.read_text(encoding="utf-8")
                if query.lower() in content.lower():
                    results.append(content)
        return results
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_memory.py -v`
预期：7 个测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/memory.py tests/unit/test_memory.py
git commit -m "feat: Memory 记忆系统——会话内 + 项目级

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 11：Agent 主循环

**目标：** 串联 LLM、ActionParser、GuardrailChain、ToolRegistry、FeedbackParser 和 Memory，形成可用 mock LLM 确定性验证的完整 agent 循环。

**颗粒度说明：** 本任务是集成任务，允许一个 subagent 单会话完成，但应按测试用例逐步实现：先停机/最大步数，再护栏拦截回灌，再工具执行与反馈回灌，最后异常处理。

**文件：**
- 创建：`src/loop.py`
- 创建：`tests/unit/test_loop.py`

**接口：**
- 消费：任务 2-10 的所有模块
- 产出：`AgentLoop` 类，`async run(task: str, llm: LLMClient, tools: ToolRegistry, guardrails: GuardrailChain, parser: ActionParser, feedback: FeedbackParser, memory: Memory, config: dict) -> Trace`

- [ ] **步骤 1：写失败测试 `tests/unit/test_loop.py`**

```python
import pytest
from src.models import Action, Message
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import DangerousCmd
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_简单读文件后停机(self, temp_project):
        # 准备：创建 agent 要读取的文件
        (temp_project / "hello.py").write_text("print('hello')")

        mock_llm = ScriptedMockLLM([
            Action(type="read_file", params={"path": str(temp_project / "hello.py")}, raw=""),
            Action(type="stop", params={"summary": "done"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("read hello.py")

        assert len(trace.steps) == 2
        assert trace.steps[0].action.type == "read_file"
        assert trace.steps[0].result is not None
        assert "hello" in trace.steps[0].result.output
        assert trace.steps[1].action.type == "stop"

    @pytest.mark.asyncio
    async def test_护栏拦截危险动作(self, temp_project):
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "rm -rf /"}, raw=""),
            Action(type="stop", params={"summary": "aborted"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("do something dangerous")

        # 第一步应被拦截
        assert trace.steps[0].guardrail.allowed is False
        assert trace.steps[0].result is None
        # 第二步应是 stop
        assert trace.steps[1].action.type == "stop"

    @pytest.mark.asyncio
    async def test_最大步数限制(self, temp_project):
        # 永不停止的 LLM
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "echo step"}, raw="")
            for _ in range(10)
        ])

        tools = ToolRegistry()
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=3,
        )

        trace = await loop.run("do something")

        assert len(trace.steps) == 3
        assert trace.end_time is not None

    @pytest.mark.asyncio
    async def test_反馈闭环_失败后修复(self, temp_project):
        # 模拟：pytest → 失败 → 修复 → pytest → 通过 → 停机
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="write_file", params={"path": str(temp_project / "calc.py"), "content": "fixed"}, raw=""),
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="stop", params={"summary": "fixed"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("fix the bug")

        assert len(trace.steps) == 4
        # Step 0: 运行 pytest
        assert trace.steps[0].action.type == "shell"
        # Step 1: 修复（应有来自 step 0 的反馈）
        assert trace.steps[1].action.type == "write_file"
        # Step 2: 再次运行 pytest
        assert trace.steps[2].action.type == "shell"
        # Step 3: 停机
        assert trace.steps[3].action.type == "stop"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_loop.py -v`
预期：FAIL

- [ ] **步骤 3：实现 `src/loop.py`**

```python
import time
import json
from src.models import Action, ToolResult, GuardrailDecision, Step, Trace, Message
from src.llm.base import LLMClient
from src.tools.registry import ToolRegistry
from src.guardrails.chain import GuardrailChain
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        guardrails: GuardrailChain,
        parser: ActionParser,
        feedback: FeedbackParser,
        memory: Memory,
        project_dir: str,
        max_steps: int = 20,
    ):
        self._llm = llm
        self._tools = tools
        self._guardrails = guardrails
        self._parser = parser
        self._feedback = feedback
        self._memory = memory
        self._project_dir = project_dir
        self._max_steps = max_steps

    async def run(self, task: str) -> Trace:
        trace = Trace(task=task, steps=[], start_time=time.time(), end_time=None)
        messages: list[Message] = []

        # 构建初始上下文
        messages.append(Message(role="system", content=self._build_system_prompt()))
        messages.append(Message(role="user", content=task))

        for step_index in range(self._max_steps):
            # 1. 调用 LLM
            llm_text = await self._llm.chat(messages)

            # 2. 解析动作
            action = self._parser.parse(llm_text, self._tools.tool_names())

            timestamp = time.time()

            # 3. 护栏检查
            guardrail = self._guardrails.check(action, self._project_dir)

            if not guardrail.allowed:
                # 被拦截——记录 step 但不执行
                step = Step(
                    index=step_index,
                    action=action,
                    guardrail=guardrail,
                    result=None,
                    feedback=None,
                    timestamp=timestamp,
                )
                trace.steps.append(step)
                self._memory.add_step(step)
                # 将拦截信息回灌给 LLM
                messages.append(Message(role="assistant", content=llm_text))
                messages.append(Message(
                    role="system",
                    content=f"[护栏拦截] {guardrail.reason}。请尝试其他方式。",
                ))
                continue

            if guardrail.requires_approval:
                # HITL：在 mock/单元测试模式下，自动拒绝以保持确定性
                # 在真实 REPL 中，会调用 hitl.prompt()
                step = Step(
                    index=step_index,
                    action=action,
                    guardrail=guardrail,
                    result=None,
                    feedback=None,
                    timestamp=timestamp,
                )
                trace.steps.append(step)
                self._memory.add_step(step)
                messages.append(Message(role="assistant", content=llm_text))
                messages.append(Message(
                    role="system",
                    content=f"[护栏需审批] {guardrail.reason}。动作未执行（非交互模式下自动拒绝）。",
                ))
                continue

            # 4. 执行工具
            if action.type == "stop":
                step = Step(
                    index=step_index,
                    action=action,
                    guardrail=guardrail,
                    result=None,
                    feedback=None,
                    timestamp=timestamp,
                )
                trace.steps.append(step)
                self._memory.add_step(step)
                break

            result = self._tools.dispatch(action, self._project_dir)

            # 5. 解析反馈
            fb = self._feedback.parse(result)

            # 6. 记录 step
            step = Step(
                index=step_index,
                action=action,
                guardrail=guardrail,
                result=result,
                feedback=fb,
                timestamp=timestamp,
            )
            trace.steps.append(step)
            self._memory.add_step(step)

            # 7. 构建下一轮反馈
            messages.append(Message(role="assistant", content=llm_text))
            messages.append(Message(
                role="system",
                content=f"""
[步骤结果]
动作: {action.type}({json.dumps(action.params)})
成功: {result.success}
输出: {result.output[:500]}
错误: {result.error or '无'}
反馈: status={fb.status}, summary={fb.summary}, suggested_action={fb.suggested_action or '无'}
""",
            ))

        trace.end_time = time.time()
        return trace

    def _build_system_prompt(self) -> str:
        tool_list = "\n".join(f"- {name}" for name in sorted(self._tools.tool_names()))
        return f"""你是一个 coding agent。你可以使用以下工具：

{tool_list}

请用 JSON 格式回复动作：
{{"type": "<工具名>", "params": {{...}}}}

要停止时使用：
{{"type": "stop", "params": {{"summary": "你做了什么"}}}}
"""
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_loop.py -v`
预期：4 个测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/loop.py tests/unit/test_loop.py
git commit -m "feat: AgentLoop 主循环——上下文→LLM→解析→护栏→执行→反馈 pipeline

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 12：HITL 控制台

**目标：** 实现需要审批时的人工确认流程，使 `requires_approval=True` 的动作能被允许、拒绝或查看详情。

**文件：**
- 创建：`src/guardrails/hitl.py`
- 修改：`tests/unit/test_guardrails.py`（追加 HITL 测试）

**接口：**
- 消费：`src/models.py` 中的 `GuardrailDecision`、`Action`
- 产出：`HITLConsole` 类，`prompt(action: Action, decision: GuardrailDecision) -> bool`（True = 批准，False = 拒绝）

- [ ] **步骤 1：在 `tests/unit/test_guardrails.py` 末尾追加 HITL 测试**

```python
from unittest.mock import patch
from src.guardrails.hitl import HITLConsole


class TestHITLConsole:
    def test_批准返回true(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive: rm",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", return_value="y"):
            result = hitl.prompt(action, decision)
        assert result is True

    def test_拒绝返回false(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive: rm",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", return_value="n"):
            result = hitl.prompt(action, decision)
        assert result is False

    def test_空输入默认拒绝(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive: rm",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", return_value=""):
            result = hitl.prompt(action, decision)
        assert result is False

    def test_detail显示详情后再次询问(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm -rf ./cache"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive command",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", side_effect=["detail", "y"]):
            result = hitl.prompt(action, decision)
        assert result is True
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_guardrails.py::TestHITLConsole -v`
预期：FAIL

- [ ] **步骤 3：实现 `src/guardrails/hitl.py`**

```python
from src.models import Action, GuardrailDecision


class HITLConsole:
    def prompt(self, action: Action, decision: GuardrailDecision) -> bool:
        print(f"\n[Guard] ⚠  {decision.reason}")
        print(f"       规则: {decision.rule_name}")
        print(f"       动作: {action.type}({action.params})")

        while True:
            choice = input("        允许执行？[y/N/detail] ").strip().lower()
            if choice == "y":
                return True
            elif choice == "detail":
                print(f"\n[Guard] 规则详情:")
                print(f"        规则名: {decision.rule_name}")
                print(f"        原因: {decision.reason}")
                print(f"        动作类型: {action.type}")
                print(f"        参数: {action.params}")
                print(f"        风险: 此操作可能导致数据丢失或安全风险\n")
                continue
            else:  # "n"、""、或其他
                return False
```

- [ ] **步骤 4：运行全部护栏测试确认通过**

运行：`pytest tests/unit/test_guardrails.py -v`
预期：全部测试 PASS（17 原有 + 4 新增 = 21）

- [ ] **步骤 5：提交**

```bash
git add src/guardrails/hitl.py tests/unit/test_guardrails.py
git commit -m "feat: HITLConsole——人机审批控制台

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 13：CLI 入口 + REPL

**目标：** 提供 `harness` 命令、单次任务模式和最小 REPL，使用户可在终端观察 agent 的每一步执行摘要。

**测试要求：** 本任务不能只做导入验证；必须先写 CLI smoke test，验证 `--help`、单次任务入口和 REPL 命令解析至少一个行为。

**文件：**
- 创建：`src/cli/main.py`
- 创建：`src/cli/repl.py`

**接口：**
- 消费：任务 2-12 的所有核心模块
- 产出：`harness` CLI 命令，支持 REPL 模式和 `--task` 单次任务模式

- [ ] **步骤 1：写失败测试 `tests/unit/test_cli.py`**

```python
import subprocess
import sys


def test_cli_help_可运行():
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.main", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Coding Agent Harness" in result.stdout
    assert "--task" in result.stdout
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_cli.py -v`
预期：FAIL，`ModuleNotFoundError` 或 CLI 入口不存在

- [ ] **步骤 3：实现 `src/cli/repl.py`**

```python
import sys
from src.models import Action, Message
from src.llm.mock import ScriptedMockLLM
from src.llm.openai import OpenAIClient
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import (
    PathSandbox, DangerousCmd, NetworkGate, FileWriteGate, DestructiveOp
)
from src.guardrails.hitl import HITLConsole
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop
from src.config import Config


class REPL:
    def __init__(self, project_dir: str = "."):
        self._project_dir = project_dir
        self._config = Config.load("config.yaml")
        self._running = False

    def run(self) -> None:
        self._running = True
        print("Coding Agent Harness REPL")
        print("输入任务描述开始，或 !help 查看命令。")
        print()

        while self._running:
            try:
                line = input("harness> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue

            if line.startswith("!"):
                self._handle_command(line)
            else:
                self._handle_task(line)

    def _handle_command(self, line: str) -> None:
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "!help":
            print("命令列表:")
            print("  !help        - 显示帮助")
            print("  !trace       - 查看最近一次 trace 摘要")
            print("  !config      - 查看当前配置")
            print("  !exit        - 退出 REPL")
            print()
            print("或直接输入任务描述来启动 agent。")
        elif cmd == "!exit":
            self._running = False
        elif cmd == "!config":
            import json
            print(json.dumps(self._config, indent=2, default=str))
        elif cmd == "!trace":
            print("暂无 trace（请先运行一个任务）")
        else:
            print(f"未知命令: {cmd}")

    def _handle_task(self, task: str) -> None:
        print(f"\n[Agent] 开始任务: {task}")
        # 构建组件
        tools = self._build_tools()
        guardrails = self._build_guardrails()
        llm = self._build_llm()

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory(
            max_recent_steps=self._config["memory"]["max_recent_steps"],
            project_dir=self._config["memory"]["project_dir"],
        )

        loop = AgentLoop(
            llm=llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=self._project_dir,
            max_steps=self._config["loop"]["max_steps"],
        )

        import asyncio
        trace = asyncio.run(loop.run(task))

        # 打印 trace 摘要
        print(f"\n[Agent] 完成，共 {len(trace.steps)} 步:")
        for step in trace.steps:
            status = "✓" if step.guardrail.allowed else "✗ 拦截"
            if step.guardrail.requires_approval:
                status = "? 审批"
            print(f"  [{step.index}] {step.action.type} {status}")
            if step.feedback:
                print(f"       → {step.feedback.status}: {step.feedback.summary}")
        print()

    def _build_tools(self) -> ToolRegistry:
        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})
        return tools

    def _build_guardrails(self) -> GuardrailChain:
        chain = GuardrailChain()
        rules_config = self._config["guardrails"]["rules"]
        chain.add_rule(PathSandbox(), enabled=rules_config["path_sandbox"]["enabled"])
        chain.add_rule(DangerousCmd(), enabled=rules_config["dangerous_cmd"]["enabled"])
        chain.add_rule(NetworkGate(), enabled=rules_config["network_gate"]["enabled"])
        chain.add_rule(FileWriteGate(), enabled=rules_config["file_write_gate"]["enabled"])
        chain.add_rule(DestructiveOp(), enabled=rules_config["destructive_op"]["enabled"])
        return chain

    def _build_llm(self):
        provider = self._config["llm"]["provider"]
        if provider == "openai":
            return OpenAIClient(
                model=self._config["llm"]["model"],
                base_url=self._config["llm"]["base_url"],
                max_tokens=self._config["llm"]["max_tokens"],
            )
        # 默认：返回一个只输出 stop 的 mock LLM
        return ScriptedMockLLM([Action(type="stop", params={"summary": "未配置 LLM"}, raw="")])
```

- [ ] **步骤 4：实现 `src/cli/main.py`**

```python
import argparse
import sys
from src.cli.repl import REPL


def main():
    parser = argparse.ArgumentParser(description="Coding Agent Harness")
    parser.add_argument(
        "--task", "-t", type=str, default=None,
        help="运行单次任务（非交互模式）"
    )
    parser.add_argument(
        "--project", "-p", type=str, default=".",
        help="项目目录（默认: 当前目录）"
    )
    args = parser.parse_args()

    repl = REPL(project_dir=args.project)

    if args.task:
        repl._handle_task(args.task)
    else:
        repl.run()


if __name__ == "__main__":
    main()
```

- [ ] **步骤 5：验证 CLI 可导入并通过 smoke test**

运行：`python -c "from src.cli.main import main; print('OK')"`
预期：`OK`（可能警告缺少 openai 模块——暂时没问题）

运行：`pytest tests/unit/test_cli.py -v`
预期：PASS

- [ ] **步骤 6：提交**

```bash
git add src/cli/main.py src/cli/repl.py tests/unit/test_cli.py
git commit -m "feat: CLI 入口 + REPL 交互循环

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 14：OpenAI LLM 适配器

**目标：** 实现 OpenAI 兼容 API 适配器，使用凭据模块读取 key，并通过 mock client 测试请求构造与返回解析。

**文件：**
- 创建：`src/llm/openai.py`
- 创建：`tests/unit/test_openai_llm.py`

**接口：**
- 消费：`src/llm/base.py` 中的 `LLMClient`、`src/models.py` 中的 `Message`
- 产出：`OpenAIClient` 类，实现 `LLMClient`，`async chat(messages: list[Message]) -> str`

- [ ] **步骤 1：写失败测试 `tests/unit/test_openai_llm.py`**

```python
import pytest
from unittest.mock import patch, AsyncMock
from src.models import Message
from src.llm.openai import OpenAIClient


class TestOpenAIClient:
    @pytest.mark.asyncio
    async def test_chat发送消息并返回响应(self):
        client = OpenAIClient(model="gpt-4o-mini", base_url="https://api.test.com/v1", max_tokens=100)

        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(message=AsyncMock(content='{"type": "stop", "params": {}}'))
        ]

        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create = AsyncMock(return_value=mock_response)
            result = await client.chat([Message(role="user", content="hello")])
            assert result == '{"type": "stop", "params": {}}'

    @pytest.mark.asyncio
    async def test_chat传递正确参数(self):
        client = OpenAIClient(model="test-model", base_url="https://api.test.com/v1", max_tokens=500)

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock(message=AsyncMock(content="response"))]

        with patch("openai.AsyncOpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create = AsyncMock(return_value=mock_response)

            await client.chat([
                Message(role="system", content="你是一个 coding agent"),
                Message(role="user", content="fix the bug"),
            ])

            call_kwargs = instance.chat.completions.create.call_args.kwargs
            assert call_kwargs["model"] == "test-model"
            assert call_kwargs["max_tokens"] == 500
            assert len(call_kwargs["messages"]) == 2
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_openai_llm.py -v`
预期：FAIL（缺少模块）

- [ ] **步骤 3：实现 `src/llm/openai.py`**

```python
import os
from src.models import Message
from src.llm.base import LLMClient


class OpenAIClient(LLMClient):
    def __init__(self, model: str, base_url: str, max_tokens: int = 4096):
        self._model = model
        self._base_url = base_url
        self._max_tokens = max_tokens

    async def chat(self, messages: list[Message]) -> str:
        from openai import AsyncOpenAI

        api_key = self._get_api_key()
        client = AsyncOpenAI(api_key=api_key, base_url=self._base_url)

        response = await client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=self._max_tokens,
        )

        return response.choices[0].message.content or ""

    def _get_api_key(self) -> str:
        # 优先尝试 keyring
        try:
            import keyring
            key = keyring.get_password("harness", "api_key")
            if key:
                return key
        except Exception:
            pass

        # Fallback：环境变量
        key = os.environ.get("HARNESS_API_KEY", "")
        if key:
            return key

        # 最后手段：.env 文件
        try:
            from pathlib import Path
            env_file = Path(".env")
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("HARNESS_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass

        raise RuntimeError(
            "未找到 API key。请设置 HARNESS_API_KEY 环境变量或运行 'harness key set'。"
        )
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_openai_llm.py -v`
预期：2 个测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/llm/openai.py tests/unit/test_openai_llm.py
git commit -m "feat: OpenAI 兼容适配器——keyring/env fallback

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 15：凭据管理

**目标：** 实现 keyring 主方案和环境变量 fallback，保证 API key 可安全录入、查询状态和清除且不回显明文。

**文件：**
- 创建：`src/cli/key.py`
- 创建：`tests/unit/test_key.py`

**接口：**
- 消费：`keyring` 库
- 产出：`KeyManager` 类，`set_key()`、`status()`、`clear_key()`

- [ ] **步骤 1：写失败测试 `tests/unit/test_key.py`**

```python
import pytest
from unittest.mock import patch
from src.cli.key import KeyManager


class TestKeyManager:
    def test_状态无key(self):
        with patch("keyring.get_password", return_value=None):
            mgr = KeyManager()
            info = mgr.status()
            assert info["stored"] is False

    def test_状态有key(self):
        with patch("keyring.get_password", return_value="sk-test123"):
            mgr = KeyManager()
            info = mgr.status()
            assert info["stored"] is True
            # 不能泄露明文 key
            assert "sk-test123" not in str(info)

    def test_设置key(self):
        with patch("keyring.set_password") as mock_set, \
             patch("getpass.getpass", return_value="sk-abc123"):
            mgr = KeyManager()
            mgr.set_key()
            mock_set.assert_called_once_with("harness", "api_key", "sk-abc123")

    def test_清除key(self):
        with patch("keyring.delete_password") as mock_delete, \
             patch("keyring.get_password", return_value="sk-test"):
            mgr = KeyManager()
            mgr.clear_key()
            mock_delete.assert_called_once_with("harness", "api_key")
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_key.py -v`
预期：FAIL

- [ ] **步骤 3：实现 `src/cli/key.py`**

```python
import getpass


class KeyManager:
    SERVICE = "harness"
    USERNAME = "api_key"

    def status(self) -> dict:
        try:
            import keyring
            key = keyring.get_password(self.SERVICE, self.USERNAME)
            return {
                "stored": key is not None,
                "backend": self._detect_backend(),
            }
        except Exception as e:
            return {"stored": False, "error": str(e)}

    def set_key(self) -> None:
        print("请输入你的 API key（输入将被隐藏）:")
        key = getpass.getpass("API key: ")
        if not key.strip():
            print("错误: key 不能为空")
            return
        try:
            import keyring
            keyring.set_password(self.SERVICE, self.USERNAME, key.strip())
            print("API key 已安全存储。")
        except Exception as e:
            print(f"存储 key 失败: {e}")
            print("备用方案: 设置 HARNESS_API_KEY 环境变量或 .env 文件")

    def clear_key(self) -> None:
        try:
            import keyring
            keyring.delete_password(self.SERVICE, self.USERNAME)
            print("API key 已删除。")
        except Exception as e:
            print(f"删除 key 失败: {e}")

    def _detect_backend(self) -> str:
        import platform
        system = platform.system()
        if system == "Windows":
            return "Windows Credential Manager"
        elif system == "Darwin":
            return "macOS Keychain"
        else:
            return "Linux Secret Service / keyring"
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/unit/test_key.py -v`
预期：4 个测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/cli/key.py tests/unit/test_key.py
git commit -m "feat: 凭据管理——keyring set/status/clear

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 16：WebUI

**目标：** 提供只读 Trace/Demo 查看器，满足课程交付中的可访问 WebUI 接口要求，但不实现完整交互式编程。

**测试要求：** 必须先写 FastAPI `TestClient` 失败测试，验证 `/` 返回 HTML、`/api/demo` 返回 Trace JSON、`/api/demo/guardrail` 返回护栏示例。

**文件：**
- 创建：`src/web/server.py`
- 创建：`src/web/templates/index.html`

**接口：**
- 消费：无（独立 demo 服务器）
- 产出：FastAPI Web 服务器，端口 8080，trace 查看器 + demo 触发

- [ ] **步骤 1：写失败测试 `tests/unit/test_web.py`**

```python
from fastapi.testclient import TestClient
from src.web.server import app


def test_index_返回_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Harness Demo" in response.text


def test_demo_返回_trace_json():
    client = TestClient(app)
    response = client.get("/api/demo")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]
    assert isinstance(data["steps"], list)
    assert data["steps"][0]["action"]["type"] == "shell"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_web.py -v`
预期：FAIL，`ModuleNotFoundError` 或 endpoint 不存在

- [ ] **步骤 3：实现 `src/web/server.py`**

```python
import json
import time
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Harness Demo")


@app.get("/", response_class=HTMLResponse)
async def index():
    template_path = Path(__file__).parent / "templates" / "index.html"
    return template_path.read_text(encoding="utf-8")


@app.get("/api/demo")
async def run_demo():
    """运行修复 bug 的 mock demo 并返回 trace。"""
    trace = {
        "task": "修复 test_subtract 的 bug",
        "steps": [
            {
                "index": 0,
                "action": {"type": "shell", "params": {"command": "pytest"}},
                "guardrail": {"allowed": True, "rule_name": "", "requires_approval": False},
                "result": {"success": True, "output": "1 failed, 1 passed\ntest_subtract FAILED: AssertionError: expected 2, got 8"},
                "feedback": {"status": "fail", "summary": "1 个测试失败", "suggested_action": "fix"},
            },
            {
                "index": 1,
                "action": {"type": "read_file", "params": {"path": "calculator.py"}},
                "guardrail": {"allowed": True, "rule_name": "", "requires_approval": False},
                "result": {"success": True, "output": "def subtract(a, b):\n    return a + b  # BUG!"},
                "feedback": {"status": "pass", "summary": "文件已读取", "suggested_action": None},
            },
            {
                "index": 2,
                "action": {"type": "write_file", "params": {"path": "calculator.py", "content": "def subtract(a, b):\n    return a - b"}},
                "guardrail": {"allowed": True, "rule_name": "FileWriteGate", "requires_approval": True},
                "result": None,
                "feedback": None,
            },
            {
                "index": 3,
                "action": {"type": "write_file", "params": {"path": "calculator.py", "content": "def subtract(a, b):\n    return a - b"}},
                "guardrail": {"allowed": True, "rule_name": "", "requires_approval": False},
                "result": {"success": True, "output": "written"},
                "feedback": {"status": "pass", "summary": "文件已写入", "suggested_action": None},
            },
            {
                "index": 4,
                "action": {"type": "shell", "params": {"command": "pytest"}},
                "guardrail": {"allowed": True, "rule_name": "", "requires_approval": False},
                "result": {"success": True, "output": "2 passed in 0.3s"},
                "feedback": {"status": "pass", "summary": "全部测试通过", "suggested_action": None},
            },
            {
                "index": 5,
                "action": {"type": "stop", "params": {"summary": "修复了 subtract bug"}},
                "guardrail": {"allowed": True, "rule_name": "", "requires_approval": False},
                "result": None,
                "feedback": None,
            },
        ],
        "start_time": time.time() - 5,
        "end_time": time.time(),
    }
    return JSONResponse(trace)


@app.get("/api/demo/guardrail")
async def run_guardrail_demo():
    """Demo：护栏拦截危险动作。"""
    trace = {
        "task": "清理缓存",
        "steps": [
            {
                "index": 0,
                "action": {"type": "shell", "params": {"command": "rm -rf /"}},
                "guardrail": {"allowed": False, "rule_name": "DangerousCmd", "requires_approval": False,
                              "reason": "检测到危险命令: rm -rf /"},
                "result": None,
                "feedback": None,
            },
            {
                "index": 1,
                "action": {"type": "shell", "params": {"command": "rm -r ./cache/"}},
                "guardrail": {"allowed": True, "rule_name": "DestructiveOp", "requires_approval": True,
                              "reason": "可能的破坏性操作: rm -r ./cache/"},
                "result": None,
                "feedback": None,
            },
            {
                "index": 2,
                "action": {"type": "stop", "params": {"summary": "已中止——用户拒绝"}},
                "guardrail": {"allowed": True, "rule_name": "", "requires_approval": False},
                "result": None,
                "feedback": None,
            },
        ],
        "start_time": time.time() - 3,
        "end_time": time.time(),
    }
    return JSONResponse(trace)


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
```

- [ ] **步骤 4：实现 `src/web/templates/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Harness Demo</title>
<style>
  body { font-family: monospace; max-width: 900px; margin: 20px auto; padding: 0 20px; background: #1a1a2e; color: #e0e0e0; }
  h1 { color: #7c3aed; }
  .step { border-left: 3px solid #333; margin: 10px 0; padding: 10px 15px; background: #16213e; border-radius: 4px; }
  .step.blocked { border-left-color: #ef4444; background: #1f0a0a; }
  .step.approval { border-left-color: #f59e0b; background: #1f1a0a; }
  .step.stop { border-left-color: #22c55e; }
  .label { color: #888; font-size: 0.85em; }
  .value { color: #e0e0e0; }
  button { padding: 8px 16px; margin: 5px; cursor: pointer; background: #7c3aed; color: white; border: none; border-radius: 4px; }
  button:hover { background: #6d28d9; }
  #trace { margin-top: 20px; }
</style>
</head>
<body>
<h1>🛡️ Coding Agent Harness — Demo</h1>
<p>最小 WebUI，用于 Trace 查看和机制演示。</p>
<div>
  <button onclick="loadDemo('/api/demo')">运行修复 Bug Demo</button>
  <button onclick="loadDemo('/api/demo/guardrail')">运行护栏 Demo</button>
</div>
<div id="trace"></div>

<script>
async function loadDemo(url) {
  document.getElementById('trace').innerHTML = '<p>加载中...</p>';
  const resp = await fetch(url);
  const trace = await resp.json();
  renderTrace(trace);
}

function renderTrace(trace) {
  let html = `<h2>任务: ${trace.task}</h2>`;
  html += `<p>步骤数: ${trace.steps.length} | 耗时: ${(trace.end_time - trace.start_time).toFixed(1)}s</p>`;
  for (const step of trace.steps) {
    let cls = 'step';
    if (!step.guardrail.allowed) cls += ' blocked';
    if (step.guardrail.requires_approval) cls += ' approval';
    if (step.action.type === 'stop') cls += ' stop';

    html += `<div class="${cls}">`;
    html += `<div><span class="label">[${step.index}]</span> <strong>${step.action.type}</strong> ${JSON.stringify(step.action.params)}</div>`;
    html += `<div><span class="label">护栏:</span> ${step.guardrail.allowed ? '✅ 放行' : '❌ 拦截'} ${step.guardrail.rule_name ? '(' + step.guardrail.rule_name + ')' : ''} ${step.guardrail.requires_approval ? '⚠ 需审批' : ''}</div>`;
    if (step.result) {
      html += `<div><span class="label">结果:</span> ${step.result.success ? '✅' : '❌'} ${step.result.output?.substring(0, 100) || ''}</div>`;
    }
    if (step.feedback) {
      html += `<div><span class="label">反馈:</span> ${step.feedback.status} — ${step.feedback.summary}</div>`;
    }
    if (step.guardrail.reason) {
      html += `<div><span class="label">原因:</span> ${step.guardrail.reason}</div>`;
    }
    html += `</div>`;
  }
  document.getElementById('trace').innerHTML = html;
}
</script>
</body>
</html>
```

- [ ] **步骤 5：验证 WebUI 可启动并通过 endpoint 测试**

运行：`python -c "from src.web.server import app; print('OK')"`
预期：`OK`

运行：`pytest tests/unit/test_web.py -v`
预期：PASS

- [ ] **步骤 6：提交**

```bash
git add src/web/server.py src/web/templates/index.html tests/unit/test_web.py
git commit -m "feat: 最小 WebUI——Trace 查看器 + demo 触发按钮

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 17：机制演示

**目标：** 用三个 pytest demo 展示核心机制：危险命令拦截、反馈闭环驱动修复、护栏与反馈协同。

**颗粒度说明：** 若使用 subagent 并行执行，可拆成 17a/17b/17c 三个 worktree；若单会话执行，必须逐个 demo 红绿验证。

**文件：**
- 创建：`tests/demo/demo_guardrail.py`
- 创建：`tests/demo/demo_feedback_loop.py`
- 创建：`tests/demo/demo_focus_dimension.py`

**接口：**
- 消费：所有核心模块
- 产出：三个确定性演示脚本（可作为 pytest 测试运行）

- [ ] **步骤 1：实现 `tests/demo/demo_guardrail.py`**

```python
"""
Demo 1：护栏拦截危险动作。

Mock LLM 输出危险命令 → GuardrailChain 拦截 → Agent 收到拦截反馈 → Agent 尝试安全替代方案。

此测试是确定性的——不需要真实 LLM，不需要网络。
"""
import pytest
from src.models import Action
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import DangerousCmd, DestructiveOp
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TestDemoGuardrail:
    @pytest.mark.asyncio
    async def test_危险命令被拦截(self, temp_project):
        """Agent 尝试 rm -rf / → 被拦截 → 尝试安全替代 → 停机。"""
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "rm -rf /"}, raw=""),
            Action(type="shell", params={"command": "echo 'safe cleanup done'"}, raw=""),
            Action(type="stop", params={"summary": "done safely"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())
        guardrails.add_rule(DestructiveOp())

        loop = AgentLoop(
            llm=mock_llm, tools=tools, guardrails=guardrails,
            parser=ActionParser(), feedback=FeedbackParser(), memory=Memory(),
            project_dir=str(temp_project), max_steps=10,
        )

        trace = await loop.run("清理系统")

        # Step 0: rm -rf / → 被拦截
        assert trace.steps[0].guardrail.allowed is False
        assert trace.steps[0].guardrail.rule_name == "DangerousCmd"
        assert trace.steps[0].result is None

        # Step 1: 安全的 echo → 执行
        assert trace.steps[1].guardrail.allowed is True
        assert trace.steps[1].result is not None
        assert trace.steps[1].result.success is True

        # Step 2: 停机
        assert trace.steps[2].action.type == "stop"

        print("\n✅ Demo 1 通过: 护栏拦截了 rm -rf /，agent 改用安全替代方案")
```

- [ ] **步骤 2：实现 `tests/demo/demo_feedback_loop.py`**

```python
"""
Demo 2：反馈闭环——agent 收到测试失败反馈后改变行为。

ScriptedMockLLM 输出: pytest → 修复 → pytest → 停机。
第一次 pytest 的反馈（失败）被解析后回灌，agent 据此输出修复动作。
"""
import pytest
from src.models import Action
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TestDemoFeedbackLoop:
    @pytest.mark.asyncio
    async def test_反馈驱动修复(self, temp_project):
        """Agent 运行测试 → 失败 → 修复代码 → 重测 → 通过 → 停机。"""
        # 创建有 bug 的文件
        (temp_project / "calc.py").write_text("def add(a, b): return a - b  # BUG\n")

        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="write_file", params={"path": str(temp_project / "calc.py"), "content": "def add(a, b): return a + b\n"}, raw=""),
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="stop", params={"summary": "bug fixed"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()

        loop = AgentLoop(
            llm=mock_llm, tools=tools, guardrails=guardrails,
            parser=ActionParser(), feedback=FeedbackParser(), memory=Memory(),
            project_dir=str(temp_project), max_steps=10,
        )

        trace = await loop.run("修复 calc.py 中的 bug")

        # Step 0: 运行 pytest → 应有反馈
        assert trace.steps[0].action.type == "shell"
        assert trace.steps[0].feedback is not None

        # Step 1: 修复代码（write_file）
        assert trace.steps[1].action.type == "write_file"

        # Step 2: 再次运行 pytest
        assert trace.steps[2].action.type == "shell"

        # Step 3: 停机
        assert trace.steps[3].action.type == "stop"

        print("\n✅ Demo 2 通过: 反馈闭环驱动 agent 从 测试→修复→重测→停机")
```

- [ ] **步骤 3：实现 `tests/demo/demo_focus_dimension.py`**

```python
"""
Demo 3：重点维度——护栏 + 反馈协同工作。

危险动作被提出 → 拦截 → agent 收到结构化反馈 →
agent 改变策略为安全 test runner → 成功。

结合了护栏（阻止/防止）和反馈（重定向/修复）的完整流程。
"""
import pytest
from src.models import Action
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import DangerousCmd, DestructiveOp
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TestDemoFocusDimension:
    @pytest.mark.asyncio
    async def test_护栏与反馈协同(self, temp_project):
        """危险 shell → 拦截 → agent 切换为安全 test runner → 成功。"""
        mock_llm = ScriptedMockLLM([
            # Step 0: Agent 尝试危险 shell 命令
            Action(type="shell", params={"command": "rm -rf ./build/"}, raw=""),
            # Step 1: 收到拦截反馈后，agent 切换为安全 test runner
            Action(type="shell", params={"command": "pytest tests/ -v"}, raw=""),
            # Step 2: 测试通过，agent 停机
            Action(type="stop", params={"summary": "测试通过，无需清理"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())
        guardrails.add_rule(DestructiveOp())

        loop = AgentLoop(
            llm=mock_llm, tools=tools, guardrails=guardrails,
            parser=ActionParser(), feedback=FeedbackParser(), memory=Memory(),
            project_dir=str(temp_project), max_steps=10,
        )

        trace = await loop.run("清理并验证测试通过")

        # Step 0: rm -rf → 被 DestructiveOp 拦住
        assert trace.steps[0].action.type == "shell"
        assert "rm" in trace.steps[0].action.params["command"]
        assert trace.steps[0].guardrail.allowed is False
        assert trace.steps[0].result is None
        print(f"  ✓ Step 0: '{trace.steps[0].action.params['command']}' → 拦截 ({trace.steps[0].guardrail.rule_name})")

        # Step 1: agent 切换为安全的 pytest
        assert trace.steps[1].action.type == "shell"
        assert "pytest" in trace.steps[1].action.params["command"]
        assert trace.steps[1].guardrail.allowed is True
        assert trace.steps[1].result is not None
        print(f"  ✓ Step 1: '{trace.steps[1].action.params['command']}' → 放行（安全命令）")

        # Step 2: 停机
        assert trace.steps[2].action.type == "stop"
        print(f"  ✓ Step 2: agent 成功停机")

        print("\n✅ Demo 3 通过: 护栏 + 反馈协同——危险动作被拦截，agent 转向安全替代方案")
```

- [ ] **步骤 4：先运行全部 demo 确认失败**

运行：`pytest tests/demo/ -v`
预期：FAIL，demo 文件或依赖模块尚未存在时失败

- [ ] **步骤 5：运行全部 demo 确认通过**

运行：`pytest tests/demo/ -v`
预期：3 个测试 PASS

- [ ] **步骤 6：提交**

```bash
git add tests/demo/
git commit -m "feat: 机制演示——护栏拦截、反馈闭环、重点维度协同

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 18：Docker 分发

**目标：** 构建可分发镜像，并验证容器内 CLI 帮助可启动。

**测试要求：** 本任务以 Docker smoke test 作为红绿验证；实现前 `Dockerfile` 不存在时 `docker build` 应失败，写入后应成功。

**文件：**
- 创建：`Dockerfile`

**接口：**
- 消费：所有代码
- 产出：可运行的 Docker 镜像

- [ ] **步骤 1：运行构建确认失败**

运行：`docker build -t harness .`
预期：FAIL，`Dockerfile` 不存在或镜像无法构建

- [ ] **步骤 2：实现 `Dockerfile`**

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .[dev]

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY config.yaml .
COPY examples/ examples/

ENV HARNESS_API_KEY=""
ENTRYPOINT ["python", "-m", "src.cli.main"]
```

- [ ] **步骤 3：验证 Dockerfile 可构建**

运行：`docker build -t harness .`
预期：构建成功

- [ ] **步骤 4：验证 Docker 可运行**

运行：`docker run --rm harness --help`
预期：显示帮助信息

- [ ] **步骤 5：提交**

```bash
git add Dockerfile
git commit -m "feat: Dockerfile——容器分发

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 19：CI/CD

**目标：** 提供 GitLab CI 配置，明确 `unit-test` job 在 Python 3.11 环境中运行单元测试和 demo。

**测试要求：** 先写 YAML smoke check，验证文件合法且含 `unit-test`、`pytest tests/unit/`、`pytest tests/demo/`。

**文件：**
- 创建：`.gitlab-ci.yml`

**接口：**
- 消费：所有测试
- 产出：包含 `unit-test` job 的 CI pipeline

- [ ] **步骤 1：写失败测试 `tests/unit/test_ci_config.py`**

```python
from pathlib import Path

import yaml


def test_gitlab_ci_包含_unit_test_job():
    path = Path(".gitlab-ci.yml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "unit-test" in data
    script = "\n".join(data["unit-test"]["script"])
    assert "pytest tests/unit/" in script
    assert "pytest tests/demo/" in script
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_ci_config.py -v`
预期：FAIL，`.gitlab-ci.yml` 不存在

- [ ] **步骤 3：实现 `.gitlab-ci.yml`**

```yaml
unit-test:
  image: python:3.11
  before_script:
    - pip install -e .[dev]
  script:
    - pytest tests/unit/ -v --tb=short
    - pytest tests/demo/ -v --tb=short
```

- [ ] **步骤 4：验证 CI 配置是合法 YAML 并通过 smoke test**

运行：`python -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml')); print('OK')"`
预期：`OK`

运行：`pytest tests/unit/test_ci_config.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add .gitlab-ci.yml tests/unit/test_ci_config.py
git commit -m "feat: CI 配置——unit-test job

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 20：README

**目标：** 编写面向课程评审者和开发者的项目文档，覆盖安装、运行、测试、Docker、凭据安全、架构和已知限制。

**测试要求：** README 也要有文档 smoke test，确保关键命令、威胁模型和核心设计决策没有漏写。

**文件：**
- 创建：`README.md`

**接口：**
- 消费：无
- 产出：完整项目文档

- [ ] **步骤 1：写失败测试 `tests/unit/test_readme.py`**

```python
from pathlib import Path


def test_readme_包含关键章节和命令():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "Coding Agent Harness" in text
    assert "pip install -e .[dev]" in text
    assert "python -m src.cli.main" in text
    assert "docker build -t harness ." in text
    assert "威胁模型" in text
    assert "机制是代码，不是提示词" in text
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/unit/test_readme.py -v`
预期：FAIL，README 缺少关键内容

- [ ] **步骤 3：实现 `README.md`**

```markdown
# Coding Agent Harness

面向小型代码仓库的终端式 Coding Agent Harness。自己实现 agent 主循环、工具分发、护栏链、反馈闭环，全部机制可在 mock LLM 下做确定性单元测试。

核心原则：**机制是代码，不是提示词**。拦截 `rm -rf /` 的是 Python 正则，不是系统提示里的一句话。反馈解析器是确定性函数，不是 LLM 的自我评估。

## 架构

Pipeline: 上下文 → LLM → Action 解析 → 护栏链 → 工具执行 → 反馈解析 → (循环/停机)

## 快速开始

### 安装

```bash
pip install -e .[dev]
```

### 启动 REPL

```bash
harness
# 或
python -m src.cli.main
```

### 单次任务

```bash
harness --task "修复 tests/ 中失败的测试"
```

### 运行测试

```bash
make test          # 单元测试（不需要真实 LLM）
make demo          # 机制演示
```

### 启动 WebUI

```bash
python -m src.web.server
# 浏览器打开 http://localhost:8080
```

## Docker

```bash
docker build -t harness .
docker run -it -v $(pwd):/project -e HARNESS_API_KEY=$YOUR_KEY harness
```

## API Key 配置

```bash
harness key set     # 隐藏输入 → 存入 OS keyring
harness key status  # 查看存储状态（不回显明文）
harness key clear   # 删除已存储的 key
```

### 威胁模型

| 威胁 | 对策 |
|------|------|
| Key 硬编码在源码中 | `.gitignore` + keyring，绝不硬编码 |
| Key 泄露到 Git 历史 | `.env` 在 `.gitignore` 中，pre-commit 检查 |
| Key 泄露到日志 | 日志过滤 Authorization header |
| Key 通过环境变量暴露 | `.env` 仅为 fallback，README 说明明文风险 |

## 目录结构

```
src/
├── models.py          # 核心数据模型
├── loop.py            # Agent 主循环
├── actions.py         # Action 解析器
├── feedback.py        # 反馈解析器 + 传感器
├── memory.py          # 记忆系统
├── config.py          # YAML 配置加载器
├── llm/               # LLM 抽象 + mock + OpenAI
├── tools/             # 工具注册表 + 文件/shell 工具
├── guardrails/        # 护栏链 + 规则 + HITL
├── cli/               # CLI 入口 + REPL + key 管理
└── web/               # 最小 WebUI
tests/
├── unit/              # 单元测试（mock LLM，确定性）
└── demo/              # 机制演示
```

## 关键设计决策

- **Harness 内核自己实现**——没有使用 LangChain AgentExecutor、AutoGen、CrewAI 或任何框架的 agent loop
- **全部核心机制可用 mock LLM 测试**——`pytest tests/unit/` 无需网络和真实 LLM
- **护栏是确定性代码**——基于正则的规则，不是基于提示词的请求
- **反馈来自工具输出解析**——不是 LLM 的自我评估

## 已知限制

- Docker：容器内 keyring 不可用，需通过 `HARNESS_API_KEY` 环境变量传 key（见威胁模型）
- 平台：已在 Windows 测试；macOS/Linux 通过 keyring 支持
- LLM：当前仅支持 OpenAI 兼容 API
- WebUI：只读 demo 查看器；完整交互在 CLI/REPL 中
```

- [ ] **步骤 4：运行 README smoke test 确认通过**

运行：`pytest tests/unit/test_readme.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add README.md tests/unit/test_readme.py
git commit -m "docs: README——安装、使用、安全、架构说明

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 依赖关系图

```
任务 1（骨架）
 └─▶ 任务 2（数据模型）
      ├─▶ 任务 3（mock LLM）
      ├─▶ 任务 4（action 解析器）
      ├─▶ 任务 5（工具注册表 + 文件工具）
      │    └─▶ 任务 6（shell 工具）
      ├─▶ 任务 7（护栏规则）
      │    └─▶ 任务 8（护栏链 + 配置）
      │         └─▶ 任务 12（HITL 控制台）
      ├─▶ 任务 9（反馈解析器）
      └─▶ 任务 10（记忆系统）
           └─▶ 任务 11（agent 主循环）← 依赖任务 3,4,5,6,8,9,10
                ├─▶ 任务 13（CLI + REPL）
                │    └─▶ 任务 15（凭据管理）
                ├─▶ 任务 14（OpenAI 适配器）
                └─▶ 任务 17（机制演示）
                     ├─▶ 任务 16（WebUI）[静态 demo 可并行；消费真实 Trace 时需等 17]
                     ├─▶ 任务 18（Docker）[需等 CLI 可运行]
                     ├─▶ 任务 19（CI）[需等 unit/demo 测试存在]
                     └─▶ 任务 20（README）[最后同步实际命令与限制]
```

**可并行组：**
- 任务 2 完成后，任务 3、4、5、7、9、10 可并行
- 任务 5 完成后，任务 6 可开始；任务 7 完成后，任务 8 可开始；任务 8 完成后，任务 12 可开始
- 任务 3、4、5、6、8、9、10 全部完成后，任务 11 可开始
- 任务 11 完成后，任务 13、14、17 可并行；任务 13 完成后，任务 15 与任务 18 可开始
- 任务 16 若只做静态 demo，可在任务 13 后并行；若要消费真实 demo Trace，等任务 17 完成
- 任务 19 等 `tests/unit/` 与 `tests/demo/` 都存在后执行；任务 20 放在最后，确保 README 与实际命令一致

---

## 验证

全部任务完成后运行：

```bash
# 单元测试（无真实 LLM，无网络）
pytest tests/unit/ -v

# 机制演示
pytest tests/demo/ -v

# 全套
make test
# Windows fallback
python -m pytest tests/unit/ -v
```

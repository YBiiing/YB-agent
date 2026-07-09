import json
import tempfile
import time
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from src.models import Action
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import (
    PathSandbox, DangerousCmd, NetworkGate, FileWriteGate, DestructiveOp
)
from src.guardrails.hitl import AutoApproveHITL
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop

app = FastAPI(title="Harness Demo")


@app.get("/", response_class=HTMLResponse)
async def index():
    template_path = Path(__file__).parent / "templates" / "index.html"
    return template_path.read_text(encoding="utf-8")


def _build_tools() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register("read_file", read_file, {"path": "str"})
    tools.register("write_file", write_file, {"path": "str", "content": "str"})
    tools.register("shell", shell_handler, {"command": "str"})
    tools.register("stop", lambda a, p: None, {"summary": "str?"})
    return tools


def _build_guardrails() -> GuardrailChain:
    chain = GuardrailChain()
    chain.add_rule(DangerousCmd(), enabled=True)
    chain.add_rule(DestructiveOp(), enabled=True)
    chain.add_rule(PathSandbox(), enabled=True)
    chain.add_rule(FileWriteGate(), enabled=True)
    chain.add_rule(NetworkGate(), enabled=True)
    return chain


async def _run_loop(project_dir: str, actions: list[Action], task: str) -> dict:
    """用 ScriptedMockLLM 运行 agent 主循环，返回 trace dict。"""
    llm = ScriptedMockLLM(actions)
    tools = _build_tools()
    guardrails = _build_guardrails()
    parser = ActionParser()
    feedback = FeedbackParser()
    memory = Memory(max_recent_steps=10, project_dir=str(Path(project_dir) / ".harness" / "memory"))

    loop = AgentLoop(
        llm=llm,
        tools=tools,
        guardrails=guardrails,
        parser=parser,
        feedback=feedback,
        memory=memory,
        project_dir=project_dir,
        max_steps=20,
        hitl=AutoApproveHITL(),
    )
    trace = await loop.run(task)
    return trace.to_dict()


@app.get("/api/demo")
async def run_demo():
    """
    Demo 1: 反馈闭环 — Agent 修复 sample_project 中 subtract 的 bug。
    跑真实的 AgentLoop：pytest(失败) → read_file(读代码) → write_file(修复) → pytest(通过) → stop。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        # 放置有 bug 的 calculator.py
        calc_path = project_dir / "calculator.py"
        calc_path.write_text(
            "def add(a, b):\n    return a + b\n\n\n"
            "def subtract(a, b):\n    # BUG: should be a - b\n    return a + b\n",
            encoding="utf-8"
        )
        # 放置测试文件
        test_path = project_dir / "test_calculator.py"
        test_path.write_text(
            "from calculator import add, subtract\n\n\n"
            "def test_add():\n    assert add(2, 3) == 5\n\n\n"
            "def test_subtract():\n    assert subtract(5, 3) == 2\n",
            encoding="utf-8"
        )

        actions = [
            Action(type="shell", params={"command": "pytest test_calculator.py -v"}, raw=""),
            Action(type="read_file", params={"path": str(calc_path)}, raw=""),
            Action(type="write_file", params={
                "path": str(calc_path),
                "content": "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n"
            }, raw=""),
            Action(type="shell", params={"command": "pytest test_calculator.py -v"}, raw=""),
            Action(type="stop", params={"summary": "fixed subtract bug: a+b -> a-b"}, raw=""),
        ]

        trace = await _run_loop(str(project_dir), actions, "fix test_subtract failure")
        return JSONResponse(trace)


@app.get("/api/demo/guardrail")
async def run_guardrail_demo():
    """
    Demo 2: 护栏链 — 危险命令被拦截，安全命令放行。
    跑真实的 AgentLoop：rm -rf / (拦截) → echo safe (放行) → stop。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        actions = [
            Action(type="shell", params={"command": "rm -rf /"}, raw=""),
            Action(type="shell", params={"command": "echo 'safe cleanup done'"}, raw=""),
            Action(type="stop", params={"summary": "done safely"}, raw=""),
        ]
        trace = await _run_loop(tmpdir, actions, "clean up the system")
        return JSONResponse(trace)


@app.get("/api/demo/focus")
async def run_focus_demo():
    """
    Demo 3: 重点维度 — 护栏 + 反馈协同。
    危险命令被拦截 → Agent 收到拦截反馈 → 转向安全替代方案 → 成功。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        actions = [
            Action(type="shell", params={"command": "rm -rf ./build/"}, raw=""),
            Action(type="shell", params={"command": "pytest tests/ -v"}, raw=""),
            Action(type="stop", params={"summary": "tests passed, no cleanup needed"}, raw=""),
        ]
        trace = await _run_loop(tmpdir, actions, "clean up and verify tests pass")
        return JSONResponse(trace)


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()

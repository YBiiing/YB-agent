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
from fastapi.testclient import TestClient
from src.web.server import app


def test_index_返回_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Harness Demo" in response.text


def test_demo_返回_trace_json():
    """Demo 1：反馈闭环——第一步是 shell(pytest)。"""
    client = TestClient(app)
    response = client.get("/api/demo")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]
    assert isinstance(data["steps"], list)
    assert len(data["steps"]) >= 3
    # 第一步：运行 pytest
    assert data["steps"][0]["action"]["type"] == "shell"
    assert "pytest" in data["steps"][0]["action"]["params"]["command"]
    # 存在 write_file 步骤（修复）
    assert any(s["action"]["type"] == "write_file" for s in data["steps"])
    # 最后一步：stop
    assert data["steps"][-1]["action"]["type"] == "stop"


def test_guardrail_demo_返回_trace_json():
    """Demo 2：护栏拦截——第一步 rm -rf / 被 DangerousCmd 拦截。"""
    client = TestClient(app)
    response = client.get("/api/demo/guardrail")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]
    assert isinstance(data["steps"], list)
    assert len(data["steps"]) >= 2
    # 第一步：rm -rf / → 被拦截
    assert data["steps"][0]["guardrail"]["allowed"] is False
    assert data["steps"][0]["action"]["type"] == "shell"
    assert "rm -rf" in data["steps"][0]["action"]["params"]["command"]
    # 存在成功执行的步骤
    assert any(
        s.get("result") is not None and s["result"].get("success")
        for s in data["steps"]
    )


def test_focus_demo_返回_trace_json():
    """Demo 3：护栏+反馈协同——第一步命中 DestructiveOp 需审批，第二步转向安全命令。"""
    client = TestClient(app)
    response = client.get("/api/demo/focus")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]
    assert isinstance(data["steps"], list)
    assert len(data["steps"]) >= 2
    # 第一步：rm -rf ./build/ → DestructiveOp 需审批
    assert data["steps"][0]["guardrail"]["requires_approval"] is True
    assert "rm" in data["steps"][0]["action"]["params"]["command"]
    # 第二步：转向安全的 pytest
    assert data["steps"][1]["guardrail"]["allowed"] is True
    assert data["steps"][1]["action"]["type"] == "shell"
    # 最后一步：stop
    assert data["steps"][-1]["action"]["type"] == "stop"

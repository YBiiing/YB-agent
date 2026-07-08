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


def test_guardrail_demo_返回_trace_json():
    client = TestClient(app)
    response = client.get("/api/demo/guardrail")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]
    assert isinstance(data["steps"], list)
    assert data["steps"][0]["guardrail"]["allowed"] is False
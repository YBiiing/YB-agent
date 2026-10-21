import json

import httpx
import keyring
import pytest

from src.v2.controller import RunState, Task
from src.v2.deepseek import DeepSeekModel, DeepSeekSettings, load_api_key
from src.v2.engine import Engine
from src.v2.model import ModelError, ModelInput
from src.v2.report import run_report
from src.v2.tools import ReadOnlyTools


def completion(*, content=None, calls=None, finish=None, usage=True):
    result = {
        "id": "synthetic-response", "model": "synthetic-model", "object": "chat.completion",
        "created": 0, "choices": [{
            "index": 0, "finish_reason": finish or ("tool_calls" if calls else "stop"),
            "message": {"role": "assistant", "content": content, "tool_calls": calls},
        }],
    }
    if usage:
        result["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    return result


def tool(call_id="native-call", arguments='{"path":"data.txt"}'):
    return {"id": call_id, "type": "function", "function": {"name": "read_file", "arguments": arguments}}


def adapter(tmp_path, handler, *, format="native"):
    return DeepSeekModel(
        DeepSeekSettings(format=format), ReadOnlyTools(tmp_path).definitions,
        api_key="offline-synthetic-key", transport=httpx.MockTransport(handler),
    )


async def test_native_sdk_multistep_roundtrip_preserves_complete_assistant_and_tool_results(tmp_path):
    (tmp_path / "data.txt").write_bytes(b"next.txt")
    (tmp_path / "next.txt").write_bytes(b"42")
    received = []

    def handler(request):
        body = json.loads(request.content)
        assert body["max_tokens"] == 1024
        assert body["thinking"] == {"type": "disabled"}
        assert body["model"] == "deepseek-chat"
        received.append(body)
        if len(received) == 1:
            value = completion(content="I will inspect the index", calls=[tool(arguments=' { "path": "data.txt" } ')])
            value["choices"][0]["message"]["reasoning_content"] = "synthetic provider metadata"
        elif len(received) == 2:
            assistant, observation = body["messages"][-2:]
            assert assistant["content"] == "I will inspect the index"
            assert assistant["reasoning_content"] == "synthetic provider metadata"
            assert assistant["tool_calls"][0]["function"]["arguments"] == ' { "path": "data.txt" } '
            assert observation["tool_call_id"] == "native-call"
            assert json.loads(json.loads(observation["content"])["output"])["content"] == "next.txt"
            value = completion(calls=[tool("second-call", '{"path":"next.txt"}')])
        else:
            assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "tool", "assistant", "tool"]
            assert "42" in body["messages"][-1]["content"]
            value = completion(content="答案为 42，来源 next.txt")
        return httpx.Response(200, json=value)

    model = adapter(tmp_path, handler)
    try:
        engine = Engine("find answer", model, ReadOnlyTools(tmp_path))
        run = await engine.execute()
        assert run.state is RunState.COMPLETED
        assert engine.model_requests == len(received) == 3
        assert engine.model_ledger.charged_tokens == 45
        assert all(item.phase == "OBSERVED" for item in engine.model_ledger.attempts)
    finally:
        await model.close()


async def test_json_protocol_uses_user_observations_without_fabricating_native_calls(tmp_path):
    (tmp_path / "data.txt").write_bytes(b"42")
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert "tools" not in body
        if count == 1:
            value = {"kind": "tools", "calls": [{"name": "read_file", "arguments": {"path": "data.txt"}}]}
        else:
            assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "user"]
            assert "external_tool_observations" in body["messages"][-1]["content"]
            value = {"kind": "final", "text": "观察到 42"}
        return httpx.Response(200, json=completion(content=json.dumps(value)))

    model = adapter(tmp_path, handler, format="json")
    try:
        run = await Engine("inspect", model, ReadOnlyTools(tmp_path)).execute()
        assert run.state is RunState.COMPLETED
    finally:
        await model.close()


@pytest.mark.parametrize("status,code", [(401, "MODEL_AUTH_ERROR"), (429, "MODEL_RATE_LIMIT"), (503, "MODEL_HTTP_ERROR")])
async def test_sdk_errors_are_single_attempt_and_do_not_leak_response_or_key(tmp_path, status, code):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "synthetic-sensitive-value"}})

    model = adapter(tmp_path, handler)
    try:
        engine = Engine("inspect", model, ReadOnlyTools(tmp_path))
        run = await engine.execute()
        assert calls == engine.model_requests == 1
        assert run.reason == code
        report = json.dumps(run_report(run, model_ledger=engine.model_ledger))
        assert "synthetic-sensitive-value" not in report
        assert "offline-synthetic-key" not in report
        assert engine.model_ledger.attempts[0].phase == "UNKNOWN"
    finally:
        await model.close()


@pytest.mark.parametrize("error,code", [
    (httpx.ConnectError, "MODEL_CONNECTION_ERROR"), (httpx.ReadTimeout, "MODEL_TIMEOUT"),
])
async def test_sdk_transport_errors_are_bounded_and_classified(tmp_path, error, code):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise error("synthetic-sensitive-value", request=request)

    model = adapter(tmp_path, handler)
    try:
        run = await Engine("inspect", model, ReadOnlyTools(tmp_path)).execute()
        assert run.state is RunState.FAILED
        assert run.reason == code
        assert calls == 1
    finally:
        await model.close()


@pytest.mark.parametrize("value,reason", [
    (completion(content="partial answer", finish="length"), "MODEL_OUTPUT_TRUNCATED"),
    (completion(content=""), "MODEL_PROTOCOL_ERROR"),
    (completion(calls=[tool(arguments='{"path":"a","path":"b"}')]), "MODEL_PROTOCOL_ERROR"),
    (completion(calls=[tool(arguments='{"path":NaN}')]), "MODEL_PROTOCOL_ERROR"),
    (completion(calls=[tool(arguments='[]')]), "MODEL_PROTOCOL_ERROR"),
    (completion(calls=[tool(), tool()]), "MODEL_PROTOCOL_ERROR"),
    (completion(calls=[{**tool(), "id": None}]), "MODEL_PROTOCOL_ERROR"),
    (completion(calls=[tool()], finish="stop"), "MODEL_PROTOCOL_ERROR"),
    (completion(content="refused", finish="content_filter"), "MODEL_PROTOCOL_ERROR"),
])
async def test_malformed_or_truncated_responses_never_execute_tools(tmp_path, value, reason):
    model = adapter(tmp_path, lambda request: httpx.Response(200, json=value))
    try:
        engine = Engine("inspect", model, ReadOnlyTools(tmp_path))
        run = await engine.execute()
        assert run.state is RunState.FAILED
        assert run.reason == reason
        assert engine.tool_calls == 0
        assert engine.model_ledger.charged_tokens == 15
        assert engine.model_ledger.attempts[0].phase == "OBSERVED_ERROR"
    finally:
        await model.close()


async def test_empty_choices_and_missing_usage_are_explicit(tmp_path):
    value = completion(content="unused")
    value["choices"] = []
    value.pop("usage")
    model = adapter(tmp_path, lambda request: httpx.Response(200, json=value))
    try:
        engine = Engine("inspect", model, ReadOnlyTools(tmp_path))
        run = await engine.execute()
        assert run.reason == "MODEL_PROTOCOL_ERROR"
        assert engine.model_ledger.attempts[0].phase == "UNKNOWN"
        assert engine.model_ledger.charged_tokens > 0
    finally:
        await model.close()


@pytest.mark.parametrize("url", [
    "http://api.deepseek.com/v1", "https://other.example/v1", "https://api.deepseek.com.evil/v1",
    "https://user:secret@api.deepseek.com/v1", "https://api.deepseek.com/v1?token=secret",
])
def test_credentials_cannot_be_redirected_by_legacy_base_url(url):
    with pytest.raises(ModelError, match="MODEL_CONFIGURATION_ERROR"):
        DeepSeekSettings(base_url=url)


def test_configuration_requires_explicit_matching_provider_and_model(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("llm:\n  provider: deepseek\n  model: deepseek-chat\n  base_url: https://api.deepseek.com/v1\n", encoding="utf-8")
    assert DeepSeekSettings.from_file(path, model="deepseek-chat").model == "deepseek-chat"
    with pytest.raises(ModelError):
        DeepSeekSettings.from_file(path, model="another-model")
    with pytest.raises(ModelError):
        DeepSeekSettings.from_file(tmp_path / "missing", model="deepseek-chat")


def test_credentials_are_explicit_and_do_not_read_project_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.setattr(keyring, "get_password", lambda *args: None)
    (tmp_path / ".env").write_text("HARNESS_API_KEY=unused-synthetic-value", encoding="utf-8")
    with pytest.raises(ModelError, match="MODEL_CREDENTIAL_MISSING"):
        load_api_key()
    monkeypatch.setenv("HARNESS_API_KEY", "  offline-synthetic-key  ")
    assert load_api_key() == "offline-synthetic-key"


async def test_preparation_is_offline_and_input_is_a_billable_full_payload(tmp_path):
    def handler(request):
        pytest.fail("prepare must not send")

    model = adapter(tmp_path, handler)
    try:
        prepared = model.prepare(ModelInput(Task("inspect"), ()))
        assert prepared.billable
        assert prepared.max_output_tokens == 1024
        assert prepared.payload["tools"][0]["function"]["name"] == "read_file"
        assert "offline-synthetic-key" not in prepared.payload_json
    finally:
        await model.close()

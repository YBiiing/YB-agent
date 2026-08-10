import sys

import pytest

from src.config import Config
from src.guardrails.hitl import AutoApproveHITL
from src.models import Action
from src.runtime import HarnessFactory


@pytest.mark.asyncio
async def test_runtime_factory_supports_respond_action(temp_project):
    config = Config.defaults()
    loop = HarnessFactory(config=config, project_dir=str(temp_project)).build_loop(
        actions=[
            Action(type="respond", params={"message": "我是 Coding Agent Harness。"}, raw="")
        ]
    )

    trace = await loop.run("你是谁")

    assert len(trace.steps) == 1
    assert trace.steps[0].action.type == "respond"
    assert trace.steps[0].action.params["message"] == "我是 Coding Agent Harness。"


@pytest.mark.asyncio
async def test_runtime_factory_applies_shell_timeout_config(temp_project):
    config = Config.defaults()
    config["loop"]["tool_timeout_sec"] = 1
    loop = HarnessFactory(config=config, project_dir=str(temp_project)).build_loop(
        hitl=AutoApproveHITL(),
        actions=[
            Action(
                type="shell",
                params={
                    "command": f'"{sys.executable}" -c "import time; time.sleep(10)"'
                },
                raw="",
            )
        ],
    )

    trace = await loop.run("run slow command")

    assert trace.steps[0].result is not None
    assert trace.steps[0].result.success is False
    assert "timeout" in trace.steps[0].result.error.lower()


@pytest.mark.asyncio
async def test_runtime_factory_applies_allowed_command_policy(temp_project):
    config = Config.defaults()
    config["tools"]["allowed_commands"] = ["pytest"]
    loop = HarnessFactory(config=config, project_dir=str(temp_project)).build_loop(
        hitl=AutoApproveHITL(),
        actions=[
            Action(type="shell", params={"command": "python script.py"}, raw=""),
        ],
    )

    trace = await loop.run("run a non-whitelisted command")

    assert trace.steps[0].guardrail.requires_approval is True
    assert trace.steps[0].guardrail.rule_name == "AllowedCommand"

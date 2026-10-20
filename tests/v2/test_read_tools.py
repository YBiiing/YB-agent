import hashlib
import json
import os
import subprocess

import pytest

from src.v2.protocol import ResultStatus, ToolCall
from src.v2.tools import ReadOnlyTools


def read(path):
    return ToolCall("read_file", {"path": path})


def test_read_preserves_content_and_hash_without_modifying_project(tmp_path):
    content = "first\n第二行\n"
    (tmp_path / "sample.txt").write_bytes(content.encode("utf-8"))
    tool = ReadOnlyTools(tmp_path)
    assert tool.authorize(read("sample.txt"))
    result = tool.execute(read("sample.txt"))
    assert result.status is ResultStatus.SUCCESS
    assert json.loads(result.output) == {
        "path": "sample.txt", "content": content, "bytes": len(content.encode()),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    assert list(tmp_path.iterdir()) == [tmp_path / "sample.txt"]


@pytest.mark.parametrize("path", [
    "../outside.txt", "/etc/passwd", "C:\\private.txt", "\\\\host\\share\\file",
    "file.txt:stream", "a/../file.txt", "a//file.txt", "./file", "file.", "file ",
    ".env", ".git/config", "nested/.env.local", "CONFIG.YAML", "auth.json",
    "secret.txt", "credentials.json", "id.key", "server.pem", "NUL", "COM1.txt", "",
    "CREDEN~1.JSO",
])
def test_sensitive_or_escaping_paths_never_return_content(tmp_path, path):
    tool = ReadOnlyTools(tmp_path)
    assert not tool.authorize(read(path))
    result = tool.execute(read(path))
    assert result.status is ResultStatus.DENIED
    assert result.output == ""


def test_missing_binary_large_and_directory_are_explicit_feedback(tmp_path):
    tool = ReadOnlyTools(tmp_path, max_read_bytes=8)
    assert tool.execute(read("missing.txt")).error == "FILE_NOT_FOUND"
    (tmp_path / "large.txt").write_bytes(b"a" * 9)
    assert tool.execute(read("large.txt")).error == "FILE_TOO_LARGE"
    (tmp_path / "binary.bin").write_bytes(b"\xff")
    assert tool.execute(read("binary.bin")).error == "UTF8_REQUIRED"
    (tmp_path / "folder").mkdir()
    assert tool.execute(read("folder")).status is ResultStatus.DENIED


def test_hard_link_cannot_read_external_content(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("external", encoding="utf-8")
    os.link(outside, project / "alias.txt")
    result = ReadOnlyTools(project).execute(read("alias.txt"))
    assert result.status is ResultStatus.DENIED
    assert result.output == ""


@pytest.mark.parametrize("directory", [False, True])
def test_symlink_file_or_parent_is_denied(tmp_path, directory):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.txt").write_text("external", encoding="utf-8")
    try:
        (project / "alias").symlink_to(
            outside if directory else outside / "data.txt", target_is_directory=directory,
        )
    except OSError:
        pytest.skip("this host cannot create symlinks")
    path = "alias/data.txt" if directory else "alias"
    tool = ReadOnlyTools(project)
    assert not tool.authorize(read(path))
    assert tool.execute(read(path)).status is ResultStatus.DENIED


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_directory_junction_is_denied(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.txt").write_text("external", encoding="utf-8")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(project / "alias"), str(outside)],
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0
    tool = ReadOnlyTools(project)
    assert not tool.authorize(read("alias/data.txt"))
    assert tool.execute(read("alias/data.txt")).status is ResultStatus.DENIED


@pytest.mark.parametrize("call", [
    ToolCall("write_file", {"path": "data.txt"}),
    ToolCall("read_file", {"path": "data.txt", "extra": True}),
    ToolCall("read_file", {"path": 1}),
    ToolCall("read_file", {"path": "data.txt"}, version="2"),
])
def test_unregistered_tools_versions_and_invalid_arguments_are_denied(tmp_path, call):
    tool = ReadOnlyTools(tmp_path)
    assert not tool.authorize(call)
    assert tool.execute(call).status is ResultStatus.DENIED

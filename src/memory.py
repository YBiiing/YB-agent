import time
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

    # ── 项目级记忆：约定 ──

    def write_convention(self, key: str, content: str) -> None:
        self._project_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._project_dir / f"{key}.md"
        filepath.write_text(content, encoding="utf-8")

    def get_convention(self, key: str) -> str | None:
        filepath = self._project_dir / f"{key}.md"
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def load_conventions(self) -> str:
        """加载默认约定文件 conventions.md。"""
        filepath = self._project_dir / "conventions.md"
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return ""

    # ── 项目级记忆：决策 ──

    def record_decision(self, summary: str, detail: str) -> None:
        """记录一条架构/设计决策到 decisions/ 目录。"""
        decisions_dir = self._project_dir / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = f"{timestamp}-{self._slugify(summary[:30])}.md"
        content = f"""# 决策: {summary}

**时间:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}

{detail}
"""
        (decisions_dir / filename).write_text(content, encoding="utf-8")

    # ── 项目级记忆：失败记录 ──

    def record_failure(self, step_desc: str, fix_desc: str) -> None:
        """记录一次失败及其修复方案到 failures/ 目录。"""
        failures_dir = self._project_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = f"{timestamp}-{self._slugify(step_desc[:30])}.md"
        content = f"""# 失败记录

**时间:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}

## 失败描述
{step_desc}

## 修复方案
{fix_desc}
"""
        (failures_dir / filename).write_text(content, encoding="utf-8")

    # ── 检索 ──

    def search(self, query: str) -> list[str]:
        results = []
        if self._project_dir.exists():
            for filepath in self._project_dir.rglob("*.md"):
                try:
                    content = filepath.read_text(encoding="utf-8")
                    if query.lower() in content.lower():
                        results.append(content)
                except Exception:
                    pass
        return results

    @staticmethod
    def _slugify(text: str) -> str:
        """将文本转为文件名安全的 slug。"""
        import re
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        return text.strip('-').lower() or "record"
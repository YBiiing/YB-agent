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
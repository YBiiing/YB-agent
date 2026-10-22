"""Bounded local audit snapshots; integrity checks are not a recovery protocol."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Callable

from src.v2.controller import RunState, TERMINAL
from src.v2.protocol import new_id


MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 4096
MAX_ARTIFACTS = 128
_ID = re.compile(r"[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class ArchiveError(Exception):
    """Credential-free public code; do not expose raw OS errors or record text."""


def _json(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n").encode("utf-8")


def _decode(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate archive key")
            value[key] = item
        return value

    def constant(value):
        raise ValueError("nonfinite archive value")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def _path(path: Path, *, directory=False, missing=False):
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if missing and item == path:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ArchiveError("ARCHIVE_LINK_DENIED")
        if item == path:
            if directory:
                if not stat.S_ISDIR(info.st_mode):
                    raise ArchiveError("ARCHIVE_DIRECTORY_REQUIRED")
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ArchiveError("ARCHIVE_REGULAR_SINGLE_LINK_REQUIRED")


def _read(path):
    _path(path)
    before = path.stat(follow_symlinks=False)
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ArchiveError("ARCHIVE_FILE_CHANGED")
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > MAX_FILE_BYTES:
        raise ArchiveError("ARCHIVE_SIZE_LIMIT")
    if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ArchiveError("ARCHIVE_FILE_CHANGED")
    return raw


def _descriptor(raw):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _events(report, run_id):
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1 or report.get("run_id") != run_id:
        raise ArchiveError("ARCHIVE_REPORT_IDENTITY")
    RunState(report["state"])
    events = report["events"]
    if not isinstance(events, list) or not 0 < len(events) <= MAX_EVENTS:
        raise ArchiveError("ARCHIVE_EVENT_LIMIT")
    for index, event in enumerate(events):
        if (not isinstance(event, dict) or set(event) != {"sequence", "kind", "state", "control"}
                or type(event["sequence"]) is not int or event["sequence"] != index
                or not isinstance(event["kind"], str) or not event["kind"]
                or event["control"] not in ("NONE", "PAUSE", "CANCEL")):
            raise ArchiveError("ARCHIVE_EVENT_SEQUENCE")
        RunState(event["state"])
    if events[-1]["state"] != report["state"]:
        raise ArchiveError("ARCHIVE_EVENT_STATE")
    return b"".join(_json({"schema_version": 1, "run_id": run_id, **event}) for event in events)


@dataclass(frozen=True, slots=True)
class ArchiveArtifact:
    id: str
    content: str
    source_sha256: str
    original_output_truncated: bool = False

    def __post_init__(self):
        if (not isinstance(self.id, str) or _ID.fullmatch(self.id) is None
                or not isinstance(self.content, str) or not isinstance(self.source_sha256, str)
                or _DIGEST.fullmatch(self.source_sha256) is None
                or type(self.original_output_truncated) is not bool
                or hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.source_sha256):
            raise ArchiveError("ARCHIVE_ARTIFACT_INVALID")


class RunArchive:
    """One writer, new Run directory, manifest committed after bounded files.

    A checkpoint can fail between replacements. Readers then report incomplete
    evidence, never infer a successful final commit from a stale report file.
    The parent is an existing trusted operator directory outside the project.
    """

    def __init__(self, parent: Path, run_id: str, project: Path, *, sanitize: Callable):
        if not isinstance(run_id, str) or _ID.fullmatch(run_id) is None:
            raise ArchiveError("ARCHIVE_RUN_ID_INVALID")
        self.root = Path(parent).absolute() / run_id
        self.run_id = run_id
        self._sanitize = sanitize
        self._previous_events = b""
        self._closed = False
        self._failed = False
        self._generation = 0
        self._artifact_sources = {}
        try:
            project = Path(project).resolve(strict=True)
            _path(self.root.parent, directory=True)
            if self.root.resolve().is_relative_to(project):
                raise ArchiveError("ARCHIVE_INSIDE_PROJECT")
            self.root.mkdir()  # Never reuse or overwrite a previous Run.
            _path(self.root, directory=True)
        except (OSError, ValueError) as error:
            raise ArchiveError("ARCHIVE_CREATE_FAILED") from error

    def _atomic(self, name, raw):
        if len(raw) > MAX_FILE_BYTES:
            raise ArchiveError("ARCHIVE_SIZE_LIMIT")
        target = self.root / name
        temporary = self.root / (".pending-" + new_id())
        try:
            _path(self.root, directory=True)
            _path(target, missing=True)
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            _path(target, missing=True)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()  # Only this invocation's unpredictable temp.

    def checkpoint(self, report: dict, *, artifacts: tuple[ArchiveArtifact, ...] = (), final=False):
        if self._closed or self._failed:
            raise ArchiveError("ARCHIVE_WRITER_CLOSED")
        try:
            # Sanitize object strings before JSON encoding, including nested JSON
            # text supplied by adapters; no raw credential is written to temp files.
            report = self._sanitize(report)
            events = _events(report, self.run_id)
            if not events.startswith(self._previous_events):
                raise ArchiveError("ARCHIVE_EVENT_REWRITE")
            if type(final) is not bool or (final and RunState(report["state"]) not in TERMINAL):
                raise ArchiveError("ARCHIVE_FINAL_STATE_INVALID")
            if not isinstance(artifacts, tuple) or len(artifacts) > MAX_ARTIFACTS:
                raise ArchiveError("ARCHIVE_ARTIFACT_LIMIT")
            files = {"report.json": _json(report), "events.jsonl": events}
            descriptors = {}
            for artifact in artifacts:
                if not isinstance(artifact, ArchiveArtifact) or artifact.id in descriptors:
                    raise ArchiveError("ARCHIVE_ARTIFACT_INVALID")
                source = (artifact.source_sha256, artifact.original_output_truncated)
                if artifact.id in self._artifact_sources and self._artifact_sources[artifact.id] != source:
                    raise ArchiveError("ARCHIVE_ARTIFACT_CHANGED")
                name = f"artifact-{artifact.id}.txt"
                content = self._sanitize(artifact.content)
                raw = content.encode("utf-8")
                files[name] = raw
                descriptors[artifact.id] = {
                    "file": name, "source_sha256": artifact.source_sha256,
                    "original_output_truncated": artifact.original_output_truncated,
                    "redacted": content != artifact.content,
                }
            if not self._artifact_sources.keys() <= descriptors.keys():
                raise ArchiveError("ARCHIVE_ARTIFACT_OMITTED")
            if any(len(raw) > MAX_FILE_BYTES for raw in files.values()) or sum(map(len, files.values())) > MAX_TOTAL_BYTES:
                raise ArchiveError("ARCHIVE_SIZE_LIMIT")
            manifest = {
                "schema_version": 1, "run_id": self.run_id, "generation": self._generation,
                "status": "FINAL" if final else "OPEN", "event_count": len(report["events"]),
                "files": {name: _descriptor(raw) for name, raw in files.items()}, "artifacts": descriptors,
                "guarantee": "local audit only; no replay, recovery, authentication or last-event durability guarantee",
            }
            # Files first, manifest last. A partial update is explicitly unreadable
            # as a complete checkpoint; it never silently returns the old success.
            for name, raw in files.items():
                self._atomic(name, raw)
            self._atomic("manifest.json", _json(manifest))
            self._previous_events = events
            self._artifact_sources = {item.id: (item.source_sha256, item.original_output_truncated) for item in artifacts}
            self._generation += 1
            self._closed = final
        except ArchiveError:
            self._failed = True
            raise
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            self._failed = True
            raise ArchiveError("ARCHIVE_WRITE_FAILED") from error


def read_archive(root: Path) -> dict:
    """Read only. Unknown/incomplete archives cannot schedule or resume work."""
    try:
        root = Path(root).absolute()
        _path(root, directory=True)
        manifest = _decode(_read(root / "manifest.json"))
        if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
                or manifest["schema_version"] != 1
                or not isinstance(manifest.get("run_id"), str) or _ID.fullmatch(manifest["run_id"]) is None
                or manifest.get("status") not in ("OPEN", "FINAL")
                or type(manifest.get("generation")) is not int or manifest["generation"] < 0
                or not isinstance(manifest.get("files"), dict)
                or not isinstance(manifest.get("artifacts"), dict)):
            raise ArchiveError("ARCHIVE_MANIFEST_INVALID")
        files, artifacts = manifest["files"], manifest["artifacts"]
        expected = {"report.json", "events.jsonl"}
        if len(artifacts) > MAX_ARTIFACTS:
            raise ArchiveError("ARCHIVE_ARTIFACT_LIMIT")
        for identity, artifact in artifacts.items():
            name = f"artifact-{identity}.txt"
            if (not isinstance(identity, str) or _ID.fullmatch(identity) is None or not isinstance(artifact, dict)
                    or artifact.get("file") != name or type(artifact.get("redacted")) is not bool
                    or type(artifact.get("original_output_truncated")) is not bool
                    or not isinstance(artifact.get("source_sha256"), str)
                    or _DIGEST.fullmatch(artifact["source_sha256"]) is None):
                raise ArchiveError("ARCHIVE_ARTIFACT_INVALID")
            expected.add(name)
        if set(files) != expected:
            raise ArchiveError("ARCHIVE_FILE_SET_INVALID")
        contents = {}
        total = 0
        for name, descriptor in files.items():
            raw = _read(root / name)
            if (not isinstance(descriptor, dict) or type(descriptor.get("bytes")) is not int
                    or descriptor != _descriptor(raw)):
                raise ArchiveError("ARCHIVE_CHECKSUM_MISMATCH")
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                raise ArchiveError("ARCHIVE_SIZE_LIMIT")
            contents[name] = raw
        for artifact in artifacts.values():
            if not artifact["redacted"] and artifact["source_sha256"] != files[artifact["file"]]["sha256"]:
                raise ArchiveError("ARCHIVE_ARTIFACT_SOURCE_MISMATCH")
        report = _decode(contents["report.json"])
        events = _events(report, manifest["run_id"])
        if (events != contents["events.jsonl"] or type(manifest.get("event_count")) is not int
                or manifest["event_count"] != len(report["events"])):
            raise ArchiveError("ARCHIVE_EVENT_MISMATCH")
        if manifest["status"] == "FINAL" and RunState(report["state"]) not in TERMINAL:
            raise ArchiveError("ARCHIVE_FINAL_STATE_INVALID")
        # Re-read commit marker: a concurrent checkpoint must not produce a mix.
        if _decode(_read(root / "manifest.json")) != manifest:
            raise ArchiveError("ARCHIVE_CHANGED_DURING_READ")
        return {
            "schema_version": 1, "integrity": "VERIFIED", "run_id": manifest["run_id"],
            "record_status": "FINALIZED" if manifest["status"] == "FINAL" else "UNFINISHED_OR_INTERRUPTED",
            "report": report, "manifest": manifest,
            "note": "Unfinished may still be running or have been interrupted. No automatic recovery; inspect effects manually.",
        }
    except ArchiveError as error:
        return {"schema_version": 1, "integrity": "INCOMPLETE", "reason": str(error)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return {"schema_version": 1, "integrity": "INCOMPLETE", "reason": "ARCHIVE_READ_FAILED"}

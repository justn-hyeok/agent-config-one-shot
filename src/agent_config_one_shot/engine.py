"""Plan and journal small filesystem changes; never execute agents or skills."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid
import warnings

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .adapters import ADAPTERS


class ConfigError(Exception):
    """A bounded error whose message contains no configuration values."""


def exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(path: Path) -> dict:
    if path.is_symlink():
        return {"kind": "link", "target": str(path.readlink())}
    if path.is_file():
        return {"kind": "file", "sha256": digest(path.read_bytes()),
                "mode": stat.S_IMODE(path.stat().st_mode)}
    if path.is_dir():
        return {"kind": "dir"}
    if exists(path):
        raise ConfigError(f"Unsupported filesystem object: {path}")
    return {"kind": "absent"}


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, indent=2) + "\n").encode())


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ConfigError(f"Invalid control file: {path}") from None
    if not isinstance(result, dict):
        raise ConfigError(f"Invalid control file: {path}")
    return result


def yaml_object(data: str, label: Path) -> tuple[YAML, dict]:
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    parser.allow_duplicate_keys = False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = parser.load(data)
    except (YAMLError, ValueError, Warning):
        raise ConfigError(f"Invalid YAML structure: {label}") from None
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise ConfigError(f"Expected a YAML object: {label}")
    return parser, result


def yaml_bytes(parser: YAML, value: dict, label: Path) -> bytes:
    output = io.StringIO()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            parser.dump(value, output)
    except (YAMLError, ValueError, Warning):
        raise ConfigError(f"Unsupported YAML serialization: {label}") from None
    return output.getvalue().encode()


def detached_yaml(value, label: Path):
    """Separate owned mutable values from aliases used by unrelated settings."""
    result = deepcopy(value)
    seen = set()

    def clear(item):
        if id(item) in seen:
            return
        seen.add(id(item))
        if hasattr(item, "yaml_set_anchor"):
            item.yaml_set_anchor(None)
        if isinstance(item, dict):
            if getattr(item, "merge", None):
                raise ConfigError(f"YAML merges inside GJC skills require manual configuration: {label}")
            for key, child in item.items():
                clear(key)
                clear(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                clear(child)

    clear(result)
    return result


def frontmatter(raw: str, label: Path) -> str:
    lines = raw.lstrip('\ufeff').splitlines(keepends=True)
    delimiter = re.compile(r'---[ \t]*(?:\r?\n)?')
    if not lines or delimiter.fullmatch(lines[0]) is None:
        raise ConfigError(f"Missing skill frontmatter: {label}")
    for index, line in enumerate(lines[1:], 1):
        if delimiter.fullmatch(line):
            return ''.join(lines[1:index])
    raise ConfigError(f"Missing closing skill frontmatter delimiter: {label}")


def gjc_settings(path: Path, skills_root: Path) -> bytes | None:
    if path.is_symlink():
        # Native config may already be managed elsewhere. Follow its current
        # authoritative target; the operation is still bounded to this home.
        path = path.resolve()
    original = path.read_text() if path.exists() else ""
    parser, settings = yaml_object(original, path)
    skills = settings.get("skills", {})
    if not isinstance(skills, dict):
        raise ConfigError(f"Unsupported GJC skills setting: {path}")
    directories = skills.get("customDirectories", [])
    if not isinstance(directories, list) or not all(isinstance(value, str) for value in directories):
        raise ConfigError(f"Unsupported GJC customDirectories setting: {path}")
    if str(skills_root) in directories:
        return None
    # Both the skills mapping and its list may be aliased elsewhere. Detach
    # each mutation point so only skills.customDirectories changes.
    owned_skills = detached_yaml(skills, path)
    owned_directories = detached_yaml(directories, path)
    owned_directories.append(str(skills_root))
    owned_skills['customDirectories'] = owned_directories
    settings['skills'] = owned_skills
    return yaml_bytes(parser, settings, path)


@dataclass
class Operation:
    kind: str
    path: Path
    target: Path | None = None
    data: bytes | None = field(default=None, repr=False)
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)

    def public(self) -> dict:
        result = {"kind": self.kind, "path": str(self.path)}
        if self.target is not None:
            result["target"] = str(self.target)
        return result

    def record(self) -> dict:
        return {**self.public(), "before": self.before, "after": self.after}


@dataclass
class Plan:
    harnesses: list[str]
    operations: list[Operation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {"harnesses": self.harnesses,
                "changes": [operation.public() for operation in self.operations],
                "notes": self.notes, "sources": self.sources}


class Manager:
    def __init__(self, home: Path, root: Path | None = None):
        self.home = home.expanduser().resolve()
        if not self.home.is_dir():
            raise ConfigError("The selected home must be an existing directory")
        requested_root = root.expanduser() if root else self.home / ".agents/agent-config-one-shot"
        if requested_root.is_symlink():
            raise ConfigError("The control root must not be a symbolic link")
        self.root = requested_root.resolve()
        if self.root == self.home or self.home.is_relative_to(self.root):
            raise ConfigError("The control root must not contain the selected home")
        for adapter in ADAPTERS.values():
            if self.root.is_relative_to(self.home / Path(adapter.skills).parent):
                raise ConfigError("The control root must be outside native harness homes")
        self.state_file = self.root / "state.json"

    def writable(self, path: Path) -> None:
        if not (path.is_relative_to(self.home) or path.is_relative_to(self.root)):
            raise ConfigError(f"Write would leave the selected home/control root: {path}")
        parent = path.parent.resolve()
        if not (parent.is_relative_to(self.home) or parent.is_relative_to(self.root)):
            raise ConfigError(f"A redirected parent would leave the selected home/control root: {path}")

    def state(self) -> dict:
        if self.state_file.is_symlink():
            raise ConfigError("The control state must not be a symbolic link")
        if not self.state_file.exists():
            return {"schema": 1, "home": str(self.home), "root": str(self.root),
                    "harnesses": [], "operations": []}
        value = read_json(self.state_file)
        if (value.get("schema") != 1 or value.get("home") != str(self.home)
                or value.get("root") != str(self.root)
                or not isinstance(value.get("operations"), list)
                or not isinstance(value.get("harnesses"), list)):
            raise ConfigError("Control state does not match this home and root")
        if (not all(isinstance(name, str) and name in ADAPTERS for name in value["harnesses"])
                or not isinstance(value.get("sources", []), list)
                or not all(isinstance(path, str) and Path(path).is_absolute() for path in value.get("sources", []))
                or not isinstance(value.get("transactions", []), list)
                or not all(isinstance(identifier, str) and re.fullmatch(r"[0-9a-f]{32}", identifier)
                           for identifier in value.get("transactions", []))):
            raise ConfigError("Invalid control state metadata")
        return value

    def pending(self) -> list[Path]:
        directory = self.root / "journals"
        if not directory.is_dir():
            return []
        return [path for path in sorted(directory.glob("*.json"))
                if read_json(path).get("phase") not in {"committed", "rolled-back", "restored"}]

    @contextmanager
    def lock(self):
        try:
            import fcntl
        except ImportError:
            raise ConfigError("Mutating commands currently require macOS or Linux") from None
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.root.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ConfigError("The control root must be owned by you with mode 0700")
        path = self.root / ".lock"
        if path.is_symlink():
            raise ConfigError("The control lock must not be a symbolic link")
        with path.open("a") as lock:
            os.chmod(path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def plan(self, harnesses: list[str], skills_source: Path | None = None) -> Plan:
        if self.pending():
            raise ConfigError("An interrupted transaction exists; run recover first")
        state = self.state()
        selected = list(dict.fromkeys(harnesses))
        if not selected:
            raise ConfigError("Select at least one harness")
        for name in selected:
            if name not in ADAPTERS:
                raise ConfigError(f"Unknown harness: {name}")
        source = (skills_source.expanduser().absolute() if skills_source
                  else self.home / ".agents/skills")
        resolved_source = source.resolve()
        if (resolved_source == self.root or resolved_source.is_relative_to(self.root)
                or self.root.is_relative_to(resolved_source)):
            raise ConfigError("Skills source and control root must not contain one another")
        if exists(source) and not source.is_dir():
            raise ConfigError("Skills source must be a directory")
        if skills_source is not None and not source.is_dir():
            raise ConfigError("The requested skills source does not exist")
        skill_files = []
        if source.is_dir():
            if (source / "SKILL.md").is_file():
                skill_files = [source / "SKILL.md"]
            else:
                skill_files = [child / "SKILL.md" for child in sorted(source.iterdir())
                               if not child.name.startswith(".") and (child / "SKILL.md").is_file()]
        plan = Plan(selected, sources=[str(path.absolute()) for path in skill_files])
        planned_paths: dict[Path, Operation] = {}

        def add(operation: Operation):
            self.writable(operation.path)
            previous = planned_paths.get(operation.path)
            if previous is not None:
                if previous.after != operation.after:
                    raise ConfigError(f"Conflicting planned changes: {operation.path}")
                return
            planned_paths[operation.path] = operation
            plan.operations.append(operation)

        def directory(path: Path):
            if exists(path):
                if not path.is_dir():
                    raise ConfigError(f"A directory path is occupied: {path}")
                return
            if path != self.root:
                directory(path.parent)
                add(Operation("mkdir", path, before={"kind": "absent"}, after={"kind": "dir"}))

        def link(path: Path, target: Path):
            if exists(path):
                if path.is_symlink() and path.resolve() == target.resolve():
                    return
                if path.exists() and target.exists() and os.path.samefile(path, target):
                    plan.notes.append(f"Existing authority preserved: {path}")
                    return
                raise ConfigError(f"Existing content conflicts with a link: {path}")
            directory(path.parent)
            add(Operation("link", path, target=target, before={"kind": "absent"},
                          after={"kind": "link", "target": str(target)}))

        def content(path: Path, data: bytes):
            before = fingerprint(path)
            if before.get("kind") == "link" or before.get("kind") == "dir":
                raise ConfigError(f"A file path has unsupported ownership: {path}")
            if before.get("kind") == "file" and before.get("sha256") == digest(data):
                return
            # Never overwrite a generated adapter that the user edited.
            if path.is_relative_to(self.root) and before.get("kind") != "absent":
                raise ConfigError(f"Generated content already exists with different bytes: {path}")
            directory(path.parent)
            mode = before.get("mode", 0o600)
            add(Operation("write", path, data=data, before=before,
                          after={"kind": "file", "sha256": digest(data), "mode": mode}))

        # Detect external edits to previously managed artifacts before adding
        # anything. Native config references do not fingerprint file contents.
        for record in state["operations"]:
            self.validate_record(record)
            if fingerprint(Path(record["path"])) != record["after"]:
                raise ConfigError(f"Managed wiring changed; inspect doctor: {record['path']}")

        shared_is_default = source.resolve() == (self.home / ".agents/skills").resolve()
        for name in selected:
            adapter = ADAPTERS[name]
            harness_root = self.root / "harnesses" / name
            directory(harness_root)
            native_skills = self.home / adapter.skills
            directory(native_skills)
            if adapter.custom_skills_config:
                if native_skills.is_symlink():
                    raise ConfigError("GJC requires its native skills root to remain a real directory")
                target_skills = harness_root / "skills"
                directory(target_skills)
                link(harness_root / "native-skills", native_skills)
                if skill_files:
                    config = self.home / adapter.custom_skills_config
                    resolved_config = config.resolve() if config.is_symlink() else config
                    self.writable(resolved_config)
                    update = gjc_settings(resolved_config, target_skills)
                    if update is not None:
                        content(resolved_config, update)
            else:
                target_skills = native_skills
                link(harness_root / "skills", native_skills)

            for relative in adapter.files + adapter.authored:
                native = self.home / relative
                planned_native = planned_paths.get(native.resolve() if native.is_symlink() else native)
                if native.exists() or (planned_native is not None and planned_native.kind == "write"):
                    link(harness_root / native.name, native)
                else:
                    plan.notes.append(f"Optional native path absent: {native}")

            if adapter.reads_shared and shared_is_default:
                plan.notes.append(f"{name} discovers the shared skills root directly")
                # Copilot needs a metadata adapter for array-valued hints.
                candidates = skill_files if name == "copilot" else []
            else:
                candidates = skill_files
            for skill_file in candidates:
                label = skill_file.parent.name
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", label):
                    raise ConfigError(f"Unsupported skill directory name: {skill_file.parent}")
                target = skill_file.parent
                if name == "copilot":
                    parser, metadata = yaml_object(frontmatter(skill_file.read_text(), skill_file), skill_file)
                    hint = metadata.get("argument-hint")
                    if isinstance(hint, list):
                        if not all(isinstance(item, str) for item in hint):
                            raise ConfigError(f"Unsupported argument hint: {skill_file}")
                        metadata["argument-hint"] = " ".join(hint)
                        header = yaml_bytes(parser, metadata, skill_file).decode()
                        target = self.root / "compat/copilot" / label
                        canonical = str(skill_file.absolute())
                        if "`" in canonical or "\n" in canonical or "\r" in canonical:
                            raise ConfigError("Skill paths used in adapters must not contain control/backtick characters")
                        body = (f"---\n{header}---\n\n"
                                f"Read `{canonical}` and follow its canonical procedure.\n"
                                f"Resolve relative resources against `{skill_file.parent.absolute()}`.\n"
                                "This adapter only normalizes metadata; task authorization still applies.\n")
                        content(target / "SKILL.md", body.encode())
                    elif adapter.reads_shared and shared_is_default:
                        continue
                link(target_skills / label, target)
        return plan

    def validate_record(self, record: dict) -> None:
        if not isinstance(record, dict) or record.get("kind") not in {"mkdir", "link", "write"}:
            raise ConfigError("Invalid managed operation")
        for key in ("path", "before", "after"):
            if key not in record:
                raise ConfigError("Incomplete managed operation")
        path = Path(record["path"])
        if not path.is_absolute() or ".." in path.parts:
            raise ConfigError("Invalid managed operation path")
        self.writable(path)
        if record["kind"] == "mkdir":
            native_roots = [self.home / adapter.skills for adapter in ADAPTERS.values()]
            native_roots.append(self.home / ".gjc/agent")
            if not path.is_relative_to(self.root) and not any(
                    native == path or native.is_relative_to(path) for native in native_roots):
                raise ConfigError("Unrecognized managed directory")
        if record["kind"] == "link" and not path.is_relative_to(self.root):
            if not any(path.parent == self.home / adapter.skills for adapter in ADAPTERS.values()):
                raise ConfigError("Unrecognized native skill link")
        if record["kind"] == "write" and not (
                (path.is_relative_to(self.root / "compat/copilot") and path.name == "SKILL.md")
                or path == (self.home / ".gjc/agent/config.yml").resolve()):
            raise ConfigError("Unrecognized managed file write")
        if record["kind"] == "link":
            target = record.get("target")
            if not isinstance(target, str) or record["after"] != {"kind": "link", "target": target}:
                raise ConfigError("Invalid managed symbolic link")

    def apply(self, harnesses: list[str], skills_source: Path | None = None) -> dict:
        with self.lock():
            plan = self.plan(harnesses, skills_source)
            state = self.state()
            if not plan.operations:
                return {"status": "unchanged", "change_count": 0, **plan.public()}
            identifier = uuid.uuid4().hex
            journal_dir = self.root / "journals"
            backup_dir = self.root / "backups" / identifier
            journal_dir.mkdir(mode=0o700, exist_ok=True)
            backup_dir.mkdir(parents=True, mode=0o700)
            journal_path = journal_dir / f"{identifier}.json"
            records = [operation.record() for operation in plan.operations]
            for index, operation in enumerate(plan.operations):
                if operation.kind == "write" and operation.before["kind"] == "file":
                    backup = backup_dir / f"{index}.bin"
                    atomic_write(backup, operation.path.read_bytes(), 0o600)
                    records[index]["backup"] = str(backup)
            journal = {"schema": 1, "id": identifier, "home": str(self.home),
                       "root": str(self.root), "phase": "applying", "operations": records,
                       "started": [], "applied": []}
            write_json(journal_path, journal)
            try:
                for index, operation in enumerate(plan.operations):
                    if fingerprint(operation.path) != operation.before:
                        raise ConfigError(f"Path changed after planning: {operation.path}")
                    journal["started"].append(index)
                    write_json(journal_path, journal)
                    if operation.kind == "mkdir":
                        operation.path.mkdir(mode=0o700)
                    elif operation.kind == "link":
                        operation.path.symlink_to(operation.target, target_is_directory=operation.target.is_dir())
                    elif operation.kind == "write":
                        atomic_write(operation.path, operation.data, operation.after["mode"])
                    journal["applied"].append(index)
                    write_json(journal_path, journal)
                state["operations"].extend(records)
                state["harnesses"] = list(dict.fromkeys(state["harnesses"] + plan.harnesses))
                state["sources"] = list(dict.fromkeys(state.get("sources", []) + plan.sources))
                state.setdefault("transactions", []).append(identifier)
                write_json(self.state_file, state)
                journal["phase"] = "committed"
                write_json(journal_path, journal)
            except (Exception, KeyboardInterrupt):
                if identifier not in self.state().get("transactions", []):
                    try:
                        self.rollback(journal)
                        journal["phase"] = "rolled-back"
                        write_json(journal_path, journal)
                    except ConfigError:
                        raise ConfigError("Installation interrupted; inspect doctor and run recover") from None
                raise
            return {"status": "installed", "change_count": len(plan.operations),
                    "transaction": identifier, "root": str(self.root), **plan.public()}

    def verify_undo(self, record: dict) -> None:
        self.validate_record(record)
        path = Path(record["path"])
        current = fingerprint(path)
        if record["kind"] == "mkdir" and current["kind"] == "dir":
            return
        if current != record["after"]:
            raise ConfigError(f"Restore would overwrite changed content: {path}")
        if record["kind"] == "write" and record["before"]["kind"] == "file":
            backup = Path(record.get("backup", ""))
            if not backup.is_relative_to(self.root / "backups") or backup.is_symlink() or not backup.is_file():
                raise ConfigError("A required private backup is missing")
            if digest(backup.read_bytes()) != record["before"]["sha256"]:
                raise ConfigError("A required private backup has changed")

    def undo(self, record: dict) -> bool:
        self.verify_undo(record)
        path = Path(record["path"])
        if record["kind"] == "mkdir":
            # New user content survives restore; control evidence is retained.
            if any(path.iterdir()):
                return False
            path.rmdir()
        elif record["kind"] == "link":
            path.unlink()
        elif record["before"]["kind"] == "absent":
            path.unlink()
        else:
            atomic_write(path, Path(record["backup"]).read_bytes(), record["before"]["mode"])
        return True

    def rollback(self, journal: dict) -> None:
        selected = []
        for index in journal["started"]:
            record = journal["operations"][index]
            self.validate_record(record)
            current = fingerprint(Path(record["path"]))
            if current == record["after"]:
                self.verify_undo(record)
                selected.append(record)
            elif current != record["before"]:
                raise ConfigError(f"Interrupted path was changed by another writer: {record['path']}")
        for record in reversed(selected):
            self.undo(record)

    def recover(self) -> dict:
        with self.lock():
            state = self.state()
            count = 0
            for path in self.pending():
                journal = read_json(path)
                if journal.get("home") != str(self.home) or journal.get("root") != str(self.root):
                    raise ConfigError("Interrupted journal has a different owner scope")
                if journal.get("phase") == "restoring":
                    self.finish_restore(journal, path)
                    state = self.state()
                    count += 1
                    continue
                if journal.get("id") in state.get("transactions", []):
                    journal["phase"] = "committed"
                else:
                    self.rollback(journal)
                    journal["phase"] = "rolled-back"
                write_json(path, journal)
                count += 1
            return {"status": "recovered" if count else "unchanged", "transactions": count}

    def doctor(self) -> dict:
        state = self.state()
        findings = []
        for record in state["operations"]:
            self.validate_record(record)
            path = Path(record["path"])
            current = fingerprint(path)
            if current != record["after"]:
                findings.append({"status": "fail", "path": str(path), "reason": "managed wiring changed"})
            elif record["kind"] == "link" and not path.exists():
                findings.append({"status": "fail", "path": str(path), "reason": "link target missing"})
        for path in self.pending():
            findings.append({"status": "fail", "path": str(path), "reason": "interrupted transaction; run recover"})
        for source in state.get("sources", []):
            if not isinstance(source, str) or not Path(source).is_file():
                findings.append({"status": "fail", "path": str(source), "reason": "shared skill source missing"})
        if self.root.exists() and (stat.S_IMODE(self.root.stat().st_mode) & 0o077):
            findings.append({"status": "fail", "path": str(self.root), "reason": "control root is not private (0700)"})
        return {"status": "fail" if findings else "ok", "installed": bool(state["operations"]),
                "harnesses": state["harnesses"], "checks": len(state["operations"]),
                "findings": findings, "scope": "filesystem wiring; no model or MCP execution"}

    def restore(self) -> dict:
        with self.lock():
            if self.pending():
                raise ConfigError("Run recover before restore")
            state = self.state()
            records = state["operations"]
            if not records:
                return {"status": "unchanged", "changes": 0}
            # Check the entire restore before removing anything.
            for record in records:
                self.verify_undo(record)
            identifier = uuid.uuid4().hex
            path = self.root / "journals" / f"restore-{identifier}.json"
            journal = {"schema": 1, "id": identifier, "home": str(self.home),
                       "root": str(self.root), "phase": "restoring",
                       "operations": records, "undone": [], "retained": []}
            write_json(path, journal)
            return self.finish_restore(journal, path)

    def finish_restore(self, journal: dict, path: Path) -> dict:
        records = journal["operations"]
        remaining = []
        # Preflight all remaining steps. A crash between mutation and its
        # checkpoint is reconciled by the original filesystem fingerprint.
        for index in range(len(records) - 1, -1, -1):
            record = records[index]
            self.validate_record(record)
            if index in journal["undone"]:
                continue
            current = fingerprint(Path(record["path"]))
            if current != record["before"]:
                self.verify_undo(record)
            remaining.append(index)
        for index in remaining:
            record = records[index]
            if fingerprint(Path(record["path"])) != record["before"]:
                if not self.undo(record):
                    journal["retained"].append(record["path"])
            journal["undone"].append(index)
            write_json(path, journal)
        state = self.state()
        state["operations"] = []
        state["harnesses"] = []
        state["sources"] = []
        write_json(self.state_file, state)
        for identifier in state.get("transactions", []):
            transaction_path = self.root / "journals" / f"{identifier}.json"
            if transaction_path.exists():
                transaction = read_json(transaction_path)
                transaction["phase"] = "restored"
                write_json(transaction_path, transaction)
        journal["phase"] = "restored"
        write_json(path, journal)
        return {"status": "restored", "changes": len(records),
                "retained_user_directories": journal["retained"]}

"""Install a built wheel in a fresh venv and exercise its public CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def run(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f"Package verification failed: {args[0]} (exit {result.returncode})")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert any(name.endswith("entry_points.txt") for name in names)
        assert not any(part in name for name in names for part in (
            "backups/", "evidence/", "__pycache__/", ".venv/", "auth.json", "settings.json"))
    if args.source:
        with tarfile.open(args.source) as archive:
            names = archive.getnames()
            assert any(name.endswith("setup.sh") for name in names)
            assert not any(part in name for name in names for part in (
                "backups/", "evidence/", "__pycache__/", ".venv/", "auth.json"))
    with tempfile.TemporaryDirectory(prefix="agent-config-wheel-") as directory:
        root = Path(directory)
        venv = root / "venv"
        run([sys.executable, "-m", "venv", str(venv)], root)
        python = venv / "bin/python"
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], root)
        cli = venv / "bin/agent-config-one-shot"
        home = root / "home"
        home.mkdir()
        source = root / "skills/hello"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("---\nname: hello\ndescription: Packaging fixture\n---\n")
        native = home / ".claude/settings.json"
        native.parent.mkdir()
        native.write_text('{"preserved":"package-fixture"}\n')
        before = native.read_bytes()

        def command(*arguments):
            result = run([str(cli), "--home", str(home), "--json", *arguments], root)
            return json.loads(result.stdout)

        listed = command("list")
        assert len(listed) == 11
        plan = command("install", "--dry-run", "--harness", "all", "--skills-source", str(source.parent))
        assert plan["status"] == "plan"
        assert not (home / ".agents/agent-config-one-shot").exists()
        installed = command("install", "--harness", "all", "--skills-source", str(source.parent))
        assert installed["status"] == "installed"
        assert command("doctor")["status"] == "ok"
        assert command("install", "--harness", "all", "--skills-source", str(source.parent))["status"] == "unchanged"
        assert native.read_bytes() == before
        assert command("restore")["status"] == "restored"
        assert command("recover")["status"] == "unchanged"
        assert command("doctor")["installed"] is False
        assert native.read_bytes() == before
        invalid = subprocess.run([str(cli), "--home", str(home), "install", "--harness", "unknown"],
                                 cwd=root, capture_output=True, text=True, timeout=15)
        assert invalid.returncode == 2
        assert "Unknown harness" in invalid.stderr
    print(json.dumps({"status": "passed", "wheel": wheel.name,
                      "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                      "checks": ["artifact allowlist", "fresh-venv installation", "11 adapters",
                                 "side-effect-free preview", "install/doctor/repeat/restore/recover",
                                 "native bytes preserved", "invalid selector rejected"]}, indent=2))


if __name__ == "__main__":
    main()

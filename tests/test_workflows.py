from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_config_one_shot.adapters import ADAPTERS
from agent_config_one_shot.engine import ConfigError, Manager, fingerprint


def snapshot(root: Path) -> dict:
    result = {}
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_dir() or path.is_symlink():
                result[str(path.relative_to(root))] = fingerprint(path)
    return result


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-config-test-")
        self.directory = Path(self.temporary.name)
        self.home = self.directory / "home"
        self.home.mkdir()
        self.skills = self.directory / "skills"
        self.skills.mkdir()
        self.skill("hello")
        self.manager = Manager(self.home)

    def tearDown(self):
        self.temporary.cleanup()

    def skill(self, name: str, extra: str = "") -> Path:
        root = self.skills / name
        root.mkdir(exist_ok=True)
        (root / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: An isolated test skill\n{extra}---\n\nCanonical body.\n")
        return root

    def native(self, relative: str, data: str) -> Path:
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agent_config_one_shot", "--home", str(self.home), "--json", *args],
            capture_output=True, text=True, timeout=20,
        )

    def test_plan_and_doctor_do_not_create_control_files(self):
        before = snapshot(self.home)
        result = self.cli("plan", "--harness", "all", "--skills-source", str(self.skills))
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(len(value["harnesses"]), 11)
        self.assertGreater(len(value["changes"]), 11)
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse(self.manager.root.exists())
        self.assertFalse(self.manager.doctor()["installed"])
        self.assertFalse(self.manager.root.exists())

    def test_all_harnesses_install_repeat_and_restore(self):
        private_files = {}
        for adapter in ADAPTERS.values():
            for relative in adapter.files:
                if relative.endswith(".toml"):
                    data = 'model = "original"\n# native preference\n'
                elif relative.endswith((".yml", ".yaml")):
                    data = '# original comment\nmodel: original\nprivateKey: fixture-secret\n'
                else:
                    data = '{"native":"fixture-secret"}\n'
                path = self.native(relative, data)
                private_files[path] = path.read_bytes()
        original_gjc = (self.home / ".gjc/agent/config.yml").read_bytes()
        self.manager.apply(list(ADAPTERS), self.skills)
        self.assertEqual(self.manager.doctor()["status"], "ok")
        for name, adapter in ADAPTERS.items():
            root = self.manager.root / "harnesses" / name
            self.assertTrue((root / "skills").is_dir(), name)
            self.assertTrue((root / "skills/hello/SKILL.md").is_file(), name)
            for relative in adapter.files:
                self.assertTrue((root / Path(relative).name).is_symlink())
        for path, original in private_files.items():
            if path != self.home / ".gjc/agent/config.yml":
                self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.home / ".gjc/agent/skills").is_symlink())
        patched_gjc = (self.home / ".gjc/agent/config.yml").read_text()
        self.assertIn("# original comment", patched_gjc)
        self.assertIn("privateKey: fixture-secret", patched_gjc)
        operation_count = len(self.manager.state()["operations"])
        repeated = self.manager.apply(list(ADAPTERS), self.skills)
        self.assertEqual(repeated["status"], "unchanged")
        self.assertEqual(len(self.manager.state()["operations"]), operation_count)
        restored = self.manager.restore()
        self.assertEqual(restored["status"], "restored")
        self.assertEqual((self.home / ".gjc/agent/config.yml").read_bytes(), original_gjc)
        self.assertEqual(self.manager.doctor()["status"], "ok")
        self.assertFalse(self.manager.doctor()["installed"])
        for path, original in private_files.items():
            self.assertEqual(path.read_bytes(), original)

    def test_default_shared_root_is_not_duplicated_for_direct_readers(self):
        shared = self.home / ".agents/skills"
        shared.mkdir(parents=True)
        (shared / "hello").symlink_to(self.skills / "hello", target_is_directory=True)
        self.manager.apply(["codex", "cursor-cli", "copilot", "amp", "cline"])
        for name in ("codex", "cursor-cli", "copilot", "amp", "cline"):
            self.assertFalse((self.home / ADAPTERS[name].skills / "hello").exists())
        self.assertTrue((shared / "hello").is_symlink())

    def test_fresh_all_harness_install_is_idempotent_immediately(self):
        self.manager.apply(list(ADAPTERS), self.skills)
        central = self.manager.root / "harnesses/gjc/config.yml"
        self.assertTrue(central.is_symlink())
        self.assertTrue(central.is_file())
        first = snapshot(self.home)
        result = self.manager.apply(list(ADAPTERS), self.skills)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["change_count"], 0)
        self.assertEqual(snapshot(self.home), first)

    def test_copilot_adapter_references_canonical_body(self):
        original = self.skill("understand", 'argument-hint: ["path", "options"]\n')
        before = (original / "SKILL.md").read_bytes()
        self.manager.apply(["copilot"], self.skills)
        adapted = self.home / ".copilot/skills/understand/SKILL.md"
        self.assertIn(str(original / "SKILL.md"), adapted.read_text())
        self.assertNotIn("Canonical body.", adapted.read_text())
        self.assertEqual((original / "SKILL.md").read_bytes(), before)
        self.manager.restore()
        self.assertFalse(adapted.exists())
        self.assertEqual((original / "SKILL.md").read_bytes(), before)

    def test_native_atomic_writes_remain_visible(self):
        native = self.native(".claude/settings.json", '{"before":true}')
        self.manager.apply(["claude"], self.skills)
        central = self.manager.root / "harnesses/claude/settings.json"
        replacement = native.with_name("replacement.json")
        replacement.write_text('{"after":true}')
        replacement.replace(native)
        self.assertEqual(json.loads(central.read_text()), {"after": True})
        self.assertEqual(self.manager.doctor()["status"], "ok")
        self.manager.restore()
        self.assertEqual(json.loads(native.read_text()), {"after": True})

    def test_conflict_is_found_before_native_mutation(self):
        conflict = self.home / ".claude/skills/hello"
        conflict.mkdir(parents=True)
        (conflict / "user.txt").write_text("user content")
        native_before = snapshot(self.home / ".claude")
        with self.assertRaises(ConfigError):
            self.manager.apply(["amp", "claude"], self.skills)
        self.assertEqual(snapshot(self.home / ".claude"), native_before)
        self.assertFalse((self.home / ".config/amp").exists())

    def test_missing_or_invalid_source_is_not_silently_ignored(self):
        with self.assertRaises(ConfigError):
            self.manager.plan(["claude"], self.directory / "missing")
        invalid = self.directory / "file"
        invalid.write_text("not a directory")
        with self.assertRaises(ConfigError):
            self.manager.plan(["claude"], invalid)

    def test_native_root_redirect_outside_home_is_refused(self):
        outside = self.directory / "outside"
        outside.mkdir()
        (self.home / ".claude").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ConfigError):
            self.manager.plan(["claude"], self.skills)
        self.assertEqual(list(outside.iterdir()), [])

    def test_native_gjc_root_must_remain_real(self):
        source = self.directory / "old-skills"
        source.mkdir()
        (self.home / ".gjc/agent").mkdir(parents=True)
        (self.home / ".gjc/agent/skills").symlink_to(source)
        with self.assertRaises(ConfigError):
            self.manager.plan(["gjc"], self.skills)

    def test_user_modified_gjc_config_blocks_entire_restore(self):
        native = self.native(".gjc/agent/config.yml", "model: initial\n")
        self.manager.apply(["gjc", "claude"], self.skills)
        native.write_text(native.read_text() + "newPreference: keep\n")
        before = snapshot(self.home)
        with self.assertRaises(ConfigError):
            self.manager.restore()
        self.assertEqual(snapshot(self.home), before)
        self.assertTrue((self.home / ".claude/skills/hello").is_symlink())

    def test_retargeted_link_blocks_restore(self):
        self.manager.apply(["claude"], self.skills)
        link = self.home / ".claude/skills/hello"
        link.unlink()
        link.symlink_to(self.directory / "changed")
        with self.assertRaises(ConfigError):
            self.manager.restore()
        self.assertEqual(link.readlink(), self.directory / "changed")

    def test_restore_preserves_new_user_files(self):
        self.manager.apply(["claude"], self.skills)
        note = self.home / ".claude/skills/user-note.txt"
        note.write_text("Keep this")
        restored = self.manager.restore()
        self.assertEqual(note.read_text(), "Keep this")
        self.assertIn(str(note.parent.resolve()), restored["retained_user_directories"])

    def test_plan_and_state_never_contain_native_secret_values(self):
        native = self.native(".gjc/agent/config.yml", "privateValue: UNIQUE-NATIVE-SECRET\n")
        plan = self.manager.plan(["gjc"], self.skills)
        self.assertNotIn("UNIQUE-NATIVE-SECRET", json.dumps(plan.public()))
        self.manager.apply(["gjc"], self.skills)
        for file in list(self.manager.root.glob("*.json")) + list((self.manager.root / "journals").glob("*.json")):
            self.assertNotIn("UNIQUE-NATIVE-SECRET", file.read_text())
        self.assertIn("UNIQUE-NATIVE-SECRET", native.read_text())
        backup = next((self.manager.root / "backups").rglob("*.bin"))
        self.assertEqual(backup.stat().st_mode & 0o077, 0)
        self.assertEqual(self.manager.root.stat().st_mode & 0o077, 0)

    def test_failure_after_native_write_rolls_back(self):
        native = self.native(".gjc/agent/config.yml", "model: before\n")
        before = native.read_bytes()
        original_symlink = Path.symlink_to
        failure_path = self.manager.root / "harnesses/gjc/config.yml"

        def fail_at_reference(path, *args, **kwargs):
            if path == failure_path:
                raise OSError("simulated native-reference failure")
            return original_symlink(path, *args, **kwargs)

        with patch.object(Path, "symlink_to", fail_at_reference):
            with self.assertRaises(OSError):
                self.manager.apply(["gjc"], self.skills)
        self.assertEqual(native.read_bytes(), before)
        self.assertEqual(self.manager.pending(), [])
        self.assertFalse(self.manager.doctor()["installed"])

    def crash(self, code: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", code, str(self.home), str(self.skills)],
                              capture_output=True, text=True, timeout=20)

    def test_process_death_during_install_is_recoverable(self):
        native = self.native(".gjc/agent/config.yml", "model: before\n")
        original = native.read_bytes()
        code = '''
import os, sys
from pathlib import Path
from unittest.mock import patch
from agent_config_one_shot.engine import Manager
m=Manager(Path(sys.argv[1])); original=Path.symlink_to
def killed(path,*args,**kwargs):
    if path == m.root/'harnesses/gjc/config.yml': os._exit(91)
    return original(path,*args,**kwargs)
with patch.object(Path,'symlink_to',killed): m.apply(['gjc'],Path(sys.argv[2]))
'''
        result = self.crash(code)
        self.assertEqual(result.returncode, 91, result.stderr)
        self.assertEqual(self.manager.doctor()["status"], "fail")
        self.assertEqual(self.manager.recover()["status"], "recovered")
        self.assertEqual(native.read_bytes(), original)
        self.assertEqual(self.manager.doctor()["status"], "ok")
        self.assertEqual(self.manager.pending(), [])

    def test_process_death_during_restore_is_recoverable(self):
        self.manager.apply(["claude"], self.skills)
        code = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from agent_config_one_shot.engine import Manager
m=Manager(Path(sys.argv[1])); original=Path.unlink
def killed(path,*args,**kwargs):
    result=original(path,*args,**kwargs)
    if path == m.home/'.claude/skills/hello': os._exit(92)
    return result
with patch.object(Path,'unlink',killed): m.restore()
'''
        result = self.crash(code)
        self.assertEqual(result.returncode, 92, result.stderr)
        self.assertEqual(self.manager.doctor()["status"], "fail")
        self.assertEqual(self.manager.recover()["status"], "recovered")
        self.assertEqual(self.manager.pending(), [])
        self.assertFalse(self.manager.doctor()["installed"])

    def test_recovery_refuses_an_external_edit(self):
        native = self.native(".gjc/agent/config.yml", "model: before\n")
        code = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from agent_config_one_shot.engine import Manager
m=Manager(Path(sys.argv[1])); original=Path.symlink_to
def killed(path,*args,**kwargs):
    if path == m.root/'harnesses/gjc/config.yml': os._exit(93)
    return original(path,*args,**kwargs)
with patch.object(Path,'symlink_to',killed): m.apply(['gjc'],Path(sys.argv[2]))
'''
        self.assertEqual(self.crash(code).returncode, 93)
        native.write_text("model: user-edit\n")
        with self.assertRaises(ConfigError):
            self.manager.recover()
        self.assertEqual(native.read_text(), "model: user-edit\n")

    def test_concurrent_installs_are_serialized(self):
        command = [sys.executable, "-m", "agent_config_one_shot", "install", "--home", str(self.home),
                   "--harness", "claude", "--skills-source", str(self.skills), "--json"]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        values = []
        for process in processes:
            output, error = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, error)
            values.append(json.loads(output)["status"])
        self.assertEqual(sorted(values), ["installed", "unchanged"])
        self.assertEqual(self.manager.doctor()["status"], "ok")

    def test_invalid_native_yaml_does_not_leak_or_mutate(self):
        self.native(".gjc/agent/config.yml", "broken: [PRIVATE-VALUE\n")
        before = snapshot(self.home / ".gjc")
        result = self.cli("install", "--harness", "gjc", "--skills-source", str(self.skills))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("PRIVATE-VALUE", result.stderr + result.stdout)
        self.assertEqual(snapshot(self.home / ".gjc"), before)

    def test_missing_master_skill_is_detected(self):
        self.manager.apply(["copilot"], self.skills)
        (self.skills / "hello/SKILL.md").unlink()
        self.assertEqual(self.manager.doctor()["status"], "fail")

    def test_tampered_state_cannot_delete_unrelated_home_file(self):
        self.manager.apply(["claude"], self.skills)
        protected = self.native(".ssh/keep", "unchanged")
        state = self.manager.state()
        state["operations"].append({"kind": "link", "path": str(protected),
                                    "target": "ignored", "before": {"kind": "absent"},
                                    "after": {"kind": "link", "target": "ignored"}})
        self.manager.state_file.write_text(json.dumps(state))
        with self.assertRaises(ConfigError):
            self.manager.restore()
        self.assertEqual(protected.read_text(), "unchanged")

    def test_all_does_not_hide_an_unknown_harness(self):
        result = self.cli("install", "--harness", "all,not-a-harness")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown harness", result.stderr)
        self.assertFalse(self.manager.root.exists())

    def test_skills_source_cannot_alias_the_control_root(self):
        self.manager.root.mkdir(parents=True, mode=0o700)
        alias = self.directory / "alias"
        alias.symlink_to(self.manager.root, target_is_directory=True)
        with self.assertRaises(ConfigError):
            self.manager.plan(["claude"], alias)

    def test_transaction_identifier_cannot_escape_control_directory(self):
        self.manager.apply(["claude"], self.skills)
        state = self.manager.state()
        state["transactions"] = ["../../outside"]
        self.manager.state_file.write_text(json.dumps(state))
        with self.assertRaises(ConfigError):
            self.manager.restore()
        self.assertTrue((self.home / ".claude/skills/hello").is_symlink())


if __name__ == "__main__":
    unittest.main()

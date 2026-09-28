from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_config_one_shot.engine as engine
from agent_config_one_shot.engine import ConfigError, Manager


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agent-review-regression-')
        self.directory = Path(self.temp.name).resolve()
        self.home = self.directory / 'home'
        self.home.mkdir()
        self.skills = self.directory / 'skills'
        (self.skills / 'hello').mkdir(parents=True)
        self.skill = self.skills / 'hello/SKILL.md'
        self.skill.write_text('---\nname: hello\ndescription: fixture\nargument-hint: [old]\n---\n')
        self.manager = Manager(self.home)
        self.native = self.home / '.gjc/agent/config.yml'

    def tearDown(self):
        self.temp.cleanup()

    def gjc(self):
        self.native.parent.mkdir(parents=True)
        self.native.write_text('model: original\n')

    def test_native_save_after_journal_checkpoint_is_preserved(self):
        self.gjc()
        original = engine.write_json
        saved = []

        def external_save(path, value):
            original(path, value)
            started = value.get('started', [])
            if not saved and value.get('phase') == 'applying' and started:
                record = value['operations'][started[-1]]
                if record['kind'] == 'write' and Path(record['path']) == self.native:
                    self.native.write_text('model: new-user-save\n')
                    saved.append(True)

        with patch.object(engine, 'write_json', external_save):
            with self.assertRaises(ConfigError):
                self.manager.apply(['gjc'], self.skills)
        self.assertTrue(saved)
        self.assertEqual(self.native.read_text(), 'model: new-user-save\n')
        self.assertFalse(self.manager.state()['operations'])
        self.assertFalse(self.manager.pending())

    def test_atomic_native_save_between_capture_and_publication_wins(self):
        self.gjc()
        original = os.link
        saved = []

        def external_save(source, target, *args, **kwargs):
            if Path(target) == self.native and Path(source).name.startswith('.agent-config-publish-'):
                self.native.write_text('model: concurrent-new-file\n')
                saved.append(True)
            return original(source, target, *args, **kwargs)

        with patch.object(engine.os, 'link', external_save):
            with self.assertRaises(ConfigError):
                self.manager.apply(['gjc'], self.skills)
        self.assertTrue(saved)
        self.assertEqual(self.native.read_text(), 'model: concurrent-new-file\n')

    def test_restore_refuses_intervening_save_without_losing_it(self):
        self.gjc()
        self.manager.apply(['gjc'], self.skills)
        original = Manager.guarded_write

        def external_save(manager, record, data, expected, action):
            if action == 'restore':
                self.native.write_text('model: save-during-restore\n')
            return original(manager, record, data, expected, action)

        with patch.object(Manager, 'guarded_write', external_save):
            with self.assertRaises(ConfigError):
                self.manager.restore()
        self.assertEqual(self.native.read_text(), 'model: save-during-restore\n')

    def test_native_open_descriptor_save_is_retained_and_diagnosed(self):
        self.gjc()
        with self.native.open('r+') as writer:
            self.manager.apply(['gjc'], self.skills)
            writer.seek(0)
            writer.write('model: late-descriptor-save\n')
            writer.truncate()
            writer.flush()
        state = self.manager.state()
        record = next(record for record in state['operations'] if record['kind'] == 'write')
        capture = Path(record['guard_dir']) / 'apply.old'
        self.assertEqual(capture.read_text(), 'model: late-descriptor-save\n')
        self.assertEqual(capture.parent.stat().st_mode & 0o077, 0)
        self.assertEqual(self.manager.doctor()['status'], 'fail')
        with self.assertRaises(ConfigError):
            self.manager.restore()

    def test_descriptor_saves_after_restore_remain_diagnosed(self):
        self.gjc()
        with self.native.open('r+') as original_writer:
            self.manager.apply(['gjc'], self.skills)
            with self.native.open('r+') as managed_writer:
                self.manager.restore()
                for writer in (original_writer, managed_writer):
                    writer.seek(0)
                    writer.write('model: saved-after-restore\n')
                    writer.truncate()
                    writer.flush()
        report = self.manager.doctor()
        self.assertFalse(report['installed'])
        self.assertEqual(report['status'], 'fail')
        retained = [finding for finding in report['findings']
                    if 'retained native config changed' in finding['reason']]
        self.assertEqual(len(retained), 2)
        for finding in retained:
            self.assertEqual(Path(finding['path']).read_text(), 'model: saved-after-restore\n')

    def test_native_creation_does_not_replace_an_appearing_file(self):
        original = os.link

        def external_save(source, target, *args, **kwargs):
            if Path(target) == self.native and Path(source).name.startswith('.agent-config-publish-'):
                self.native.write_text('model: first-native-save\n')
            return original(source, target, *args, **kwargs)

        with patch.object(engine.os, 'link', external_save):
            with self.assertRaises(ConfigError):
                self.manager.apply(['gjc'], self.skills)
        self.assertEqual(self.native.read_text(), 'model: first-native-save\n')

    def test_native_removal_preserves_save_after_restore_preflight(self):
        self.manager.apply(['gjc'], self.skills)
        original = Manager.guarded_remove

        def external_save(manager, record):
            self.native.write_text('model: saved-before-removal\n')
            return original(manager, record)

        with patch.object(Manager, 'guarded_remove', external_save):
            with self.assertRaises(ConfigError):
                self.manager.restore()
        self.assertEqual(self.native.read_text(), 'model: saved-before-removal\n')

    def test_process_death_after_native_capture_recovers(self):
        self.gjc()
        code = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from agent_config_one_shot.engine import Manager
m=Manager(Path(sys.argv[1])); original=Path.rename
def killed(path,target):
    result=original(path,target)
    if path == m.home/'.gjc/agent/config.yml': os._exit(94)
    return result
with patch.object(Path,'rename',killed): m.apply(['gjc'],Path(sys.argv[2]))
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.home), str(self.skills)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 94, result.stderr)
        self.assertFalse(self.native.exists())
        self.assertEqual(self.manager.recover()['status'], 'recovered')
        self.assertEqual(self.native.read_text(), 'model: original\n')
        self.assertEqual(self.manager.doctor()['status'], 'ok')

    def test_process_death_after_native_restore_capture_recovers(self):
        self.gjc()
        self.manager.apply(['gjc'], self.skills)
        code = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from agent_config_one_shot.engine import Manager
m=Manager(Path(sys.argv[1])); original=Path.rename
def killed(path,target):
    result=original(path,target)
    if path == m.home/'.gjc/agent/config.yml': os._exit(95)
    return result
with patch.object(Path,'rename',killed): m.restore()
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.home)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 95, result.stderr)
        self.assertEqual(self.manager.recover()['status'], 'recovered')
        self.assertEqual(self.native.read_text(), 'model: original\n')
        self.assertFalse(self.manager.doctor()['installed'])

    def test_dangling_gjc_target_parent_is_rejected_before_mutation(self):
        self.native.parent.mkdir(parents=True)
        target = self.home / 'missing-parent/gjc.yml'
        self.native.symlink_to(target)
        with self.assertRaises(ConfigError):
            self.manager.apply(['gjc'], self.skills)
        self.assertFalse(target.parent.exists())
        self.assertFalse((self.home / '.gjc/agent/skills').exists())
        self.assertFalse(self.manager.state()['operations'])

    def test_existing_redirected_gjc_target_installs_and_restores(self):
        self.native.parent.mkdir(parents=True)
        target = self.home / 'native-config/gjc.yml'
        target.parent.mkdir()
        target.write_text('model: original\n')
        self.native.symlink_to(target)
        self.manager.apply(['gjc'], self.skills)
        self.assertEqual(self.manager.doctor()['status'], 'ok')
        self.manager.restore()
        self.assertEqual(target.read_text(), 'model: original\n')
        self.assertTrue(self.native.is_symlink())

    def test_native_config_cannot_be_owned_control_content(self):
        self.native.parent.mkdir(parents=True)
        self.manager.root.mkdir(parents=True, mode=0o700)
        target = self.manager.root / 'native.yml'
        target.write_text('model: original\n')
        self.native.symlink_to(target)
        with self.assertRaises(ConfigError):
            self.manager.apply(['gjc'], self.skills)
        self.assertEqual(target.read_text(), 'model: original\n')

    def test_copilot_metadata_refreshes_repeatedly_then_restores(self):
        self.manager.apply(['copilot'], self.skills)
        adapter = self.home / '.copilot/skills/hello/SKILL.md'
        for hint in ('[new]', '[newer]', 'scalar'):
            self.skill.write_text(f'---\nname: hello\ndescription: fixture\nargument-hint: {hint}\n---\n')
            self.assertEqual(self.manager.doctor()['status'], 'fail')
            self.assertEqual(self.manager.apply(['copilot'], self.skills)['status'], 'installed')
            self.assertIn('argument-hint: '+hint.strip('[]'), adapter.read_text())
            self.assertEqual(self.manager.doctor()['status'], 'ok')
        writes = [record for record in self.manager.state()['operations'] if record['kind'] == 'write']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['before']['kind'], 'absent')
        self.manager.restore()
        self.assertFalse(adapter.exists())

    def test_user_edited_copilot_adapter_is_not_refreshed(self):
        self.manager.apply(['copilot'], self.skills)
        adapter = self.home / '.copilot/skills/hello/SKILL.md'
        adapter.write_text(adapter.read_text()+'User edit\n')
        self.skill.write_text(self.skill.read_text().replace('[old]', '[new]'))
        with self.assertRaises(ConfigError):
            self.manager.apply(['copilot'], self.skills)
        self.assertTrue(adapter.read_text().endswith('User edit\n'))

    def test_same_name_copilot_source_cannot_replace_existing_authority(self):
        self.manager.apply(['copilot'], self.skills)
        adapter = self.home / '.copilot/skills/hello/SKILL.md'
        before = adapter.read_bytes()
        state = self.manager.state_file.read_bytes()
        other = self.directory / 'other/hello'
        other.mkdir(parents=True)
        (other / 'SKILL.md').write_text(self.skill.read_text().replace('[old]', '[other]'))
        with self.assertRaisesRegex(ConfigError, 'another source'):
            self.manager.apply(['copilot'], other.parent)
        self.assertEqual(adapter.read_bytes(), before)
        self.assertEqual(self.manager.state_file.read_bytes(), state)
        self.assertEqual(self.manager.doctor()['status'], 'ok')

    def test_custom_copilot_scalar_to_array_retargets_owned_link(self):
        self.skill.write_text(self.skill.read_text().replace('[old]', 'scalar'))
        self.manager.apply(['copilot'], self.skills)
        native = self.home / '.copilot/skills/hello'
        self.assertEqual(native.resolve(), self.skill.parent)
        self.skill.write_text(self.skill.read_text().replace('scalar', '[new]'))
        self.assertEqual(self.manager.doctor()['status'], 'fail')
        self.manager.apply(['copilot'], self.skills)
        self.assertEqual(native.resolve(), self.manager.root / 'compat/copilot/hello')
        self.assertEqual(self.manager.doctor()['status'], 'ok')
        self.manager.restore()
        self.assertFalse(native.is_symlink())
        self.assertTrue(self.skill.is_file())

    def test_default_copilot_scalar_to_array_requires_adapter(self):
        shared = self.home / '.agents/skills/hello'
        shared.mkdir(parents=True)
        source = shared / 'SKILL.md'
        source.write_text(self.skill.read_text().replace('[old]', 'scalar'))
        self.manager.apply(['copilot'])
        source.write_text(source.read_text().replace('scalar', '[new]'))
        self.assertEqual(self.manager.doctor()['status'], 'fail')
        self.manager.apply(['copilot'])
        self.assertEqual(self.manager.doctor()['status'], 'ok')
        self.assertIn('argument-hint: new', (self.home / '.copilot/skills/hello/SKILL.md').read_text())

    def test_failed_link_transition_rolls_back_to_original_source(self):
        self.skill.write_text(self.skill.read_text().replace('[old]', 'scalar'))
        self.manager.apply(['copilot'], self.skills)
        native = self.home / '.copilot/skills/hello'
        self.skill.write_text(self.skill.read_text().replace('scalar', '[new]'))
        original = engine.write_json

        def fail_commit(path, value):
            if path == self.manager.state_file:
                raise OSError('fixture commit failure')
            original(path, value)

        with patch.object(engine, 'write_json', fail_commit):
            with self.assertRaises(OSError):
                self.manager.apply(['copilot'], self.skills)
        self.assertEqual(native.resolve(), self.skill.parent)
        self.assertFalse(self.manager.pending())

    def test_interrupted_copilot_link_transition_recovers(self):
        self.skill.write_text(self.skill.read_text().replace('[old]', 'scalar'))
        self.manager.apply(['copilot'], self.skills)
        self.skill.write_text(self.skill.read_text().replace('scalar', '[new]'))
        code = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from agent_config_one_shot.engine import Manager
m=Manager(Path(sys.argv[1])); original=Path.rename
def killed(path,target):
    result=original(path,target)
    if path == m.home/'.copilot/skills/hello': os._exit(97)
    return result
with patch.object(Path,'rename',killed): m.apply(['copilot'],Path(sys.argv[2]))
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.home), str(self.skills)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 97, result.stderr)
        self.assertEqual(self.manager.recover()['status'], 'recovered')
        self.assertEqual((self.home / '.copilot/skills/hello').resolve(), self.skill.parent)

    def test_failed_copilot_refresh_restores_previous_adapter(self):
        self.manager.apply(['copilot'], self.skills)
        adapter = self.home / '.copilot/skills/hello/SKILL.md'
        before = adapter.read_bytes()
        self.skill.write_text(self.skill.read_text().replace('[old]', '[new]'))
        original = engine.write_json

        def fail_commit(path, value):
            if path == self.manager.state_file:
                raise OSError('fixture commit failure')
            original(path, value)

        with patch.object(engine, 'write_json', fail_commit):
            with self.assertRaises(OSError):
                self.manager.apply(['copilot'], self.skills)
        self.assertEqual(adapter.read_bytes(), before)
        self.assertFalse(self.manager.pending())

    def test_control_directory_symlinks_are_rejected_without_external_writes(self):
        for name in ('journals', 'backups'):
            with self.subTest(name=name):
                self.manager.root.mkdir(parents=True, mode=0o700, exist_ok=True)
                outside = self.directory / name
                outside.mkdir()
                redirected = self.manager.root / name
                redirected.symlink_to(outside, target_is_directory=True)
                try:
                    with self.assertRaises(ConfigError):
                        self.manager.apply(['claude'], self.skills)
                    self.assertFalse(list(outside.iterdir()))
                    self.assertFalse((self.home / '.claude').exists())
                finally:
                    redirected.unlink()

    def test_restore_upgrades_legacy_native_write_records(self):
        self.gjc()
        self.manager.apply(['gjc'], self.skills)
        state = self.manager.state()
        for record in state['operations']:
            record.pop('guard_dir', None)
        self.manager.state_file.write_text(json.dumps(state))
        self.manager.restore()
        self.assertEqual(self.native.read_text(), 'model: original\n')

    def test_recover_upgrades_legacy_install_journal_before_native_undo(self):
        self.gjc()
        result = self.manager.apply(['gjc'], self.skills)
        journal_path = self.manager.root / 'journals' / f"{result['transaction']}.json"
        journal = json.loads(journal_path.read_text())
        journal['phase'] = 'applying'
        for record in journal['operations']:
            record.pop('guard_dir', None)
        journal_path.write_text(json.dumps(journal))
        state = self.manager.state()
        state.update(operations=[], harnesses=[], sources=[], transactions=[])
        self.manager.state_file.write_text(json.dumps(state))
        self.assertEqual(self.manager.recover()['status'], 'recovered')
        self.assertEqual(self.native.read_text(), 'model: original\n')
        self.assertFalse(self.manager.pending())

    def test_process_death_during_created_native_file_removal_recovers(self):
        self.manager.apply(['gjc'], self.skills)
        code = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from agent_config_one_shot.engine import Manager
m=Manager(Path(sys.argv[1])); original=Path.rename
def killed(path,target):
    result=original(path,target)
    if path == m.home/'.gjc/agent/config.yml': os._exit(96)
    return result
with patch.object(Path,'rename',killed): m.restore()
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.home)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 96, result.stderr)
        self.assertEqual(self.manager.recover()['status'], 'recovered')
        self.assertFalse(self.native.exists())
        self.assertFalse(self.manager.doctor()['installed'])

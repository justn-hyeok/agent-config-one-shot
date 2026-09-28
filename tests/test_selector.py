from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_config_one_shot import cli
from agent_config_one_shot.engine import Manager
from agent_config_one_shot.selector import SelectionCancelled


class SelectorRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='agent-selector-routing-')
        self.home = Path(self.temporary.name) / 'home'
        self.home.mkdir()
        self.output = io.StringIO()

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, *arguments):
        with contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(['--home', str(self.home), *arguments])

    def test_terminal_uses_choice_before_any_configuration_write(self):
        def choose(options, initial, **kwargs):
            self.assertFalse(Manager(self.home).root.exists())
            self.assertEqual(len(options), 11)
            return ['claude']
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), \
             patch.object(self.output, 'isatty', return_value=True), \
             patch.object(cli, 'choose_harnesses', side_effect=choose):
            self.assertEqual(self.call('install'), 0)
        self.assertEqual(Manager(self.home).state()['harnesses'], ['claude'])

    def test_cancel_does_not_initialize_state(self):
        with patch.object(cli, 'choose_harnesses', side_effect=SelectionCancelled):
            self.assertEqual(self.call('install', '--interactive'), 130)
        self.assertIn('no configuration changes', self.output.getvalue())
        self.assertFalse(Manager(self.home).root.exists())

    def test_explicit_harness_bypasses_screen(self):
        with patch.object(cli, 'choose_harnesses', side_effect=AssertionError('unexpected TUI')):
            self.assertEqual(self.call('install', '--harness', 'claude'), 0)

    def test_json_uses_headless_selection(self):
        with patch.object(cli, 'choose_harnesses', side_effect=AssertionError('unexpected TUI')), \
             patch.object(cli, 'harness_list', return_value=[{'id': 'claude', 'detected': True}]):
            self.assertEqual(self.call('install', '--json'), 0)
        self.assertEqual(json.loads(self.output.getvalue())['harnesses'], ['claude'])

    def test_noninteractive_uses_detected_without_screen(self):
        with patch.object(cli, 'choose_harnesses', side_effect=AssertionError('unexpected TUI')), \
             patch.object(cli, 'harness_list', return_value=[{'id': 'amp', 'detected': True}]):
            self.assertEqual(self.call('install', '--non-interactive'), 0)
        self.assertEqual(Manager(self.home).state()['harnesses'], ['amp'])

    def test_forced_screen_in_a_pipe_fails_without_writes(self):
        with patch.object(cli.sys.stdin, 'isatty', return_value=False):
            self.assertEqual(self.call('install', '--interactive'), 2)
        self.assertFalse(Manager(self.home).root.exists())

    def test_json_and_interactive_are_rejected_before_screen(self):
        with patch.object(cli, 'choose_harnesses', side_effect=AssertionError('unexpected TUI')):
            self.assertEqual(self.call('install', '--interactive', '--json'), 2)
        self.assertFalse(Manager(self.home).root.exists())

    def test_forced_screen_preselects_explicit_ids_and_preview_is_readonly(self):
        def choose(options, initial, **kwargs):
            self.assertEqual(initial, ['amp'])
            self.assertTrue(kwargs['preview'])
            return ['claude', 'copilot']
        with patch.object(cli, 'choose_harnesses', side_effect=choose):
            self.assertEqual(self.call('plan', '--interactive', '--harness', 'amp'), 0)
        self.assertFalse(Manager(self.home).root.exists())


@unittest.skipUnless(os.name == 'posix', 'PTY terminal tests require POSIX')
class TerminalSelectionTests(unittest.TestCase):
    def setUp(self):
        import fcntl
        import termios
        self.fcntl, self.termios = fcntl, termios
        self.temporary = tempfile.TemporaryDirectory(prefix='agent-selector-pty-')
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.master, self.slave = pty.openpty()
        self.original = termios.tcgetattr(self.slave)
        self.process = None
        self.resize(24, 80)
        self.transcript = b''

    def tearDown(self):
        try:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.termios.tcflush(self.slave, self.termios.TCIOFLUSH)
                self.process.wait(timeout=5)
        finally:
            os.close(self.master)
            os.close(self.slave)
            self.temporary.cleanup()

    def resize(self, rows, columns):
        self.fcntl.ioctl(self.slave, self.termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGWINCH)

    def start(self, *flags):
        environment = os.environ.copy()
        environment.update(TERM='xterm-256color', PATH=str(self.bin), LC_ALL='C.UTF-8')
        slave = self.slave
        termios, fcntl = self.termios, self.fcntl

        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        # macOS hangs up a session's PTY when its leader exits. Capture modes
        # after the real CLI returns but before that controlling process exits.
        wrapper = (
            "import sys,termios,json; from pathlib import Path; "
            "from agent_config_one_shot.cli import main; "
            "report=Path(sys.argv[1]); status=main(sys.argv[2:]); "
            "report.write_text(json.dumps(termios.tcgetattr(sys.stdin.fileno())[3])); "
            "sys.exit(status)"
        )
        self.process = subprocess.Popen(
            [sys.executable, '-c', wrapper, str(self.root / 'terminal-mode.json'),
             '--home', str(self.home), 'install', *flags],
            stdin=self.slave, stdout=self.slave, stderr=self.slave,
            env=environment, preexec_fn=controlling_terminal,
        )

    def until(self, text, timeout=8):
        expected = text.encode()
        deadline = time.monotonic() + timeout
        while expected not in self.transcript:
            if time.monotonic() >= deadline:
                self.fail('Terminal did not render '+text+'; transcript: '+repr(self.transcript[-3000:]))
            readable, _, _ = select.select([self.master], [], [], 0.05)
            if readable:
                try:
                    self.transcript += os.read(self.master, 65536)
                except OSError:
                    break
            elif self.process.poll() is not None:
                break
        self.assertIn(expected, self.transcript)

    def send(self, data):
        os.write(self.master, data)

    def finish(self, expected):
        deadline = time.monotonic() + 8
        # A real terminal continually consumes output. Drain the PTY while
        # waiting, including redraws and the post-selection CLI summary.
        while self.process.poll() is None and time.monotonic() < deadline:
            readable, _, _ = select.select([self.master], [], [], 0.05)
            if readable:
                try:
                    self.transcript += os.read(self.master, 65536)
                except OSError:
                    break
        self.assertEqual(self.process.poll(), expected, repr(self.transcript[-2500:]))
        after = json.loads((self.root / 'terminal-mode.json').read_text())
        mask = self.termios.ICANON | self.termios.ECHO
        self.assertEqual(after & mask, self.original[3] & mask)

    def test_real_terminal_multiselect_installs_only_checked_ids(self):
        self.start()
        self.until('Choose harnesses to configure')
        self.assertFalse(Manager(self.home).root.exists())
        # No executable is in the isolated PATH: initially nothing is checked.
        self.send(b'j ')
        self.send(b'j')
        self.send(b'j ')
        self.send(b'\r')
        self.finish(0)
        self.assertEqual(Manager(self.home).state()['harnesses'], ['claude', 'copilot'])
        self.assertFalse((self.home / '.codex').exists())

    def test_arrow_navigation_and_cancel_leave_no_files(self):
        self.start()
        self.until('Choose harnesses to configure')
        self.send(b'\x1bOB ')
        self.send(b'\x1b')
        self.finish(130)
        self.assertFalse(Manager(self.home).root.exists())

    def test_empty_enter_requires_a_choice(self):
        self.start()
        self.until('Choose harnesses to configure')
        self.send(b'\r')
        self.until('Choose at least one harness')
        self.assertFalse(Manager(self.home).root.exists())
        self.send(b' \r')
        self.finish(0)
        self.assertEqual(Manager(self.home).state()['harnesses'], ['codex'])

    def test_ctrl_c_restores_terminal_without_changes(self):
        self.start()
        self.until('Choose harnesses to configure')
        self.send(b'\x03')
        self.finish(130)
        self.assertFalse(Manager(self.home).root.exists())

    def test_sigterm_restores_terminal_without_changes(self):
        self.start()
        self.until('Choose harnesses to configure')
        self.process.send_signal(signal.SIGTERM)
        self.finish(130)
        self.assertFalse(Manager(self.home).root.exists())

    def test_small_terminal_can_be_resized_and_then_used(self):
        self.resize(8, 40)
        self.start()
        self.until('Resize terminal')
        self.assertFalse(Manager(self.home).root.exists())
        self.resize(24, 80)
        self.until('Space: toggle')
        self.send(b' \r')
        self.finish(0)

    def test_detected_cli_is_preselected(self):
        executable = self.bin / 'copilot'
        executable.write_text('#!/bin/sh\nexit 99\n')
        executable.chmod(0o755)
        self.start()
        self.until('1/11 selected')
        self.send(b'\r')
        self.finish(0)
        self.assertEqual(Manager(self.home).state()['harnesses'], ['copilot'])

    def test_interactive_preview_does_not_create_configuration(self):
        self.start('--dry-run')
        self.until('Choose harnesses to configure')
        self.send(b'a\r')
        self.finish(0)
        self.assertFalse(Manager(self.home).root.exists())

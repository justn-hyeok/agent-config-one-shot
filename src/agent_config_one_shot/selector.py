"""A small terminal checklist. This module never changes configuration."""
from __future__ import annotations

import os
import signal
import sys

from .engine import ConfigError


class SelectionCancelled(Exception):
    pass


def choose_harnesses(options: list[dict], initial: list[str], *, preview: bool = False) -> list[str]:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ConfigError("The selector needs a terminal. Use --harness or --non-interactive.")
    if os.environ.get("TERM", "dumb") in {"", "dumb"}:
        raise ConfigError("This terminal cannot show the selector. Use --harness or --non-interactive.")
    try:
        import curses
    except ImportError:
        raise ConfigError("Terminal selection is unavailable. Use --harness or --non-interactive.") from None

    ids = [item['id'] for item in options]
    if not ids:
        raise ConfigError("No harnesses are available to select.")
    selected = set(initial).intersection(ids)
    action = 'preview' if preview else 'configure'

    def screen(window):
        nonlocal selected
        cursor = 0
        message = ''
        window.keypad(True)
        if hasattr(curses, 'set_escdelay'):
            curses.set_escdelay(50)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

        def line(row, text, attribute=0):
            height, width = window.getmaxyx()
            if row < 0 or row >= height or width < 2:
                return
            try:
                window.addnstr(row, 0, text, width - 1, attribute)
            except curses.error:
                pass

        while True:
            window.erase()
            height, width = window.getmaxyx()
            small = height < 10 or width < 44
            line(0, 'Choose harnesses to configure', curses.A_BOLD)
            if small:
                line(2, 'Resize terminal to at least 44 x 10.')
                line(3, 'Esc / Ctrl-C: cancel without changes')
            else:
                line(1, 'CLI install and sign-in are managed separately.')
                line(2, 'Up/Down: move  Space: toggle  Enter: continue')
                line(3, 'a: all  n: none  d: detected  Esc/Ctrl-C: cancel')
                rows = height - 7
                top = max(0, min(cursor - rows + 1, len(options) - rows))
                for index in range(top, min(top + rows, len(options))):
                    item = options[index]
                    mark = '[x]' if item['id'] in selected else '[ ]'
                    status = 'CLI detected' if item['detected'] else 'CLI not found'
                    pointer = '> ' if index == cursor else '  '
                    line(4 + index - top, f"{pointer}{mark} {item['id']:<14} {status}",
                         curses.A_REVERSE if index == cursor else 0)
                line(height - 2, message)
                line(height - 1, f"{len(selected)}/{len(ids)} selected | Enter: {action} selected")
            window.refresh()
            key = window.get_wch()
            if key in ('\x1b', '\x03', 'q'):
                raise SelectionCancelled()
            if key == curses.KEY_RESIZE:
                continue
            if small:
                continue
            if key in (curses.KEY_UP, 'k'):
                cursor = (cursor - 1) % len(options)
            elif key in (curses.KEY_DOWN, 'j'):
                cursor = (cursor + 1) % len(options)
            elif key == ' ':
                if ids[cursor] in selected:
                    selected.remove(ids[cursor])
                else:
                    selected.add(ids[cursor])
            elif key == 'a':
                selected = set(ids)
            elif key == 'n':
                selected.clear()
            elif key == 'd':
                selected = {item['id'] for item in options if item['detected']}
            elif key in ('\n', '\r', curses.KEY_ENTER):
                if selected:
                    return [identifier for identifier in ids if identifier in selected]
                message = 'Choose at least one harness, or cancel.'

    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise SelectionCancelled()

    signal.signal(signal.SIGTERM, terminate)
    try:
        return curses.wrapper(screen)
    except (KeyboardInterrupt, EOFError):
        raise SelectionCancelled() from None
    except curses.error:
        raise ConfigError("Terminal selection failed. Use --harness or --non-interactive.") from None
    finally:
        signal.signal(signal.SIGTERM, previous)

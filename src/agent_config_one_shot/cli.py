"""Public CLI. Read-only commands never initialize control state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from . import __version__
from .adapters import ADAPTERS
from .engine import ConfigError, Manager
from .selector import SelectionCancelled, choose_harnesses


def context_options(parser: argparse.ArgumentParser, *, inherited: bool = False):
    defaults = argparse.SUPPRESS if inherited else None
    parser.add_argument("--home", type=Path, default=defaults,
                        help="Home to manage (default: your home; useful for isolated tests)")
    parser.add_argument("--root", type=Path, default=defaults,
                        help="Private control root (default: HOME/.agents/agent-config-one-shot)")
    parser.add_argument("--json", action="store_true",
                        default=argparse.SUPPRESS if inherited else False,
                        help="Output paths and status as JSON; never config values")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="agent-config-one-shot",
        description="Connect native agent configs and shared skills without copying credentials.",
    )
    result.add_argument("--version", action="version", version=__version__)
    context_options(result)
    commands = result.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List supported and detected harnesses")
    context_options(listing, inherited=True)
    for name, help_text in (("plan", "Preview all changes without writing"),
                            ("install", "Connect selected/detected harnesses")):
        command = commands.add_parser(name, help=help_text)
        context_options(command, inherited=True)
        command.add_argument("--harness", action="append", default=[],
                             help="Harness ID; repeat, comma-separate, or use 'all'")
        command.add_argument("--skills-source", type=Path,
                             help="Your skills directory (default: HOME/.agents/skills)")
        mode = command.add_mutually_exclusive_group()
        mode.add_argument("--interactive", action="store_true", help="Choose harnesses in a terminal checklist")
        mode.add_argument("--non-interactive", action="store_true", help="Use explicit or detected harnesses without a screen")
        if name == "install":
            command.add_argument("--dry-run", action="store_true", help="Preview without writes")
    for name, help_text in (("doctor", "Check managed wiring without agent/model calls"),
                            ("restore", "Undo managed wiring; preserve unrelated/user changes"),
                            ("recover", "Recover an interrupted filesystem transaction")):
        command = commands.add_parser(name, help=help_text)
        context_options(command, inherited=True)
    return result


def harness_list() -> list[dict]:
    result = []
    for adapter in ADAPTERS.values():
        executable = next((shutil.which(name) for name in adapter.executables if shutil.which(name)), None)
        result.append({"id": adapter.id, "detected": executable is not None,
                       "executable": executable, "shared_root_discovery": adapter.reads_shared})
    return result


def select(values: list[str]) -> list[str]:
    chosen = [part.strip() for value in values for part in value.split(",") if part.strip()]
    for name in chosen:
        if name != "all" and name not in ADAPTERS:
            raise ConfigError(f"Unknown harness: {name}")
    if "all" in chosen:
        return list(ADAPTERS)
    if not chosen:
        return [item["id"] for item in harness_list() if item["detected"]]
    return list(dict.fromkeys(chosen))


def display(value: dict | list, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2))
        return
    if isinstance(value, list):
        for item in value:
            print(f"{item['id']:<14} {'detected' if item['detected'] else 'not detected'}")
        return
    status = value.get("status", "plan")
    print(f"{status.capitalize()}: {', '.join(value.get('harnesses', [])) or 'configuration wiring'}")
    changes = value.get("changes")
    if isinstance(changes, list):
        phase = "planned" if status == "plan" else "applied"
        print(f"{len(changes)} {phase} change(s)")
        for change in changes:
            target = f" -> {change['target']}" if "target" in change else ""
            print(f"  {change['kind']:<6} {change['path']}{target}")
    elif isinstance(changes, int):
        print(f"{changes} change(s)")
    if "root" in value:
        print(f"Control root: {value['root']}")
    if "checks" in value:
        print(f"{value['checks']} check(s); scope: {value['scope']}")
        if not value["installed"]:
            print("No managed installation at this root.")
    for finding in value.get("findings", []):
        print(f"  FAIL {finding['path']}: {finding['reason']}")
    for path in value.get("retained_user_directories", []):
        print(f"  Retained directory with new content: {path}")
    for note in value.get("notes", []):
        print(f"  {note}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "list":
            display(harness_list(), args.json)
            return 0
        manager = Manager(args.home or Path.home(), args.root)
        if args.command in {"plan", "install"}:
            names = select(args.harness)
            preview = args.command == "plan" or args.dry_run
            if args.interactive and args.json:
                raise ConfigError("--interactive cannot be combined with --json. Use --harness for JSON output.")
            interactive = args.interactive or (
                not args.harness and not args.non_interactive and not args.json
                and sys.stdin.isatty() and sys.stdout.isatty())
            if interactive:
                names = choose_harnesses(harness_list(), names, preview=preview)
            if preview:
                value = {"status": "plan", **manager.plan(names, args.skills_source).public()}
            else:
                value = manager.apply(names, args.skills_source)
        elif args.command == "doctor":
            value = manager.doctor()
        elif args.command == "restore":
            value = manager.restore()
        else:
            value = manager.recover()
        display(value, args.json)
        return 1 if value.get("status") == "fail" else 0
    except SelectionCancelled:
        print("Cancelled: no configuration changes.")
        return 130
    except ConfigError as error:
        message = str(error)
    except (OSError, RuntimeError, UnicodeError, ValueError):
        message = "A filesystem or input operation failed; no configuration values were printed."
    except KeyboardInterrupt:
        message = "Interrupted. Run doctor, then recover if an incomplete transaction is reported."
    if args.json:
        print(json.dumps({"status": "error", "message": message}), file=sys.stderr)
    else:
        print(f"Error: {message}", file=sys.stderr)
    return 2

# agent-config-one-shot

English | [한국어](README.ko.md)

Set up shared agent configs across your coding harnesses in one command.

Connect your own skills to selected coding agents, keep a central view of their
native settings, and verify or undo the wiring. Authentication, sessions,
provider formats, model choices, and plugin caches stay with each harness.

**v0.2 supports macOS and Linux with Python 3.11+.** Windows installation is
not supported yet. No agent binaries or paid model requests are launched.

## Install the release

```sh
uv tool install --upgrade https://github.com/justn-hyeok/agent-config-one-shot/releases/download/v0.2.1/agent_config_one_shot-0.2.1-py3-none-any.whl
agent-config-one-shot install
agent-config-one-shot doctor
```

The release also includes a source archive and SHA256 checksums. The examples
below refer to a source checkout; the wheel provides the CLI directly.

## Try it locally

```sh
uv tool install .
agent-config-one-shot list
agent-config-one-shot plan --harness claude,copilot --skills-source ./examples/skills
agent-config-one-shot install --harness claude,copilot --skills-source ./examples/skills
agent-config-one-shot doctor
```

With your existing `~/.agents/skills`, one setup command is enough:

```sh
./setup.sh --harness claude,cursor-cli,copilot,amp
```

In a terminal, omit `--harness` to choose targets in the checklist below.
Without a terminal, omitted targets still select detected executables.
`--harness all` explicitly
selects all eleven adapters, even if the CLIs are not installed. Selecting a
harness configures paths; it does not install or authenticate that CLI.

The checkout setup wrapper requires `uv` and invokes the same locked CLI.
Once the CLI is installed, use `agent-config-one-shot install` directly.

This project is not published to a package registry yet. Install from a local
checkout or a verified wheel. `uv` is convenient, not required: `pipx install .`
or `python -m pip install .` also provides the command.

## Choose harnesses in the terminal

```sh
agent-config-one-shot install
```

The checklist shows all eleven harnesses and whether their CLI is detected.
Detected CLIs are preselected; you can select other targets or deselect any row.
Use Up/Down to move, Space to toggle, and Enter to configure the selection.
`a` selects all, `n` clears the list, and `d` selects detected CLIs.
Esc, `q`, or Ctrl-C cancels without creating configuration or control state.
An empty selection stays on the screen until you select something or cancel.

`plan` and `install --dry-run` use the same checklist for a read-only preview.
Nothing is configured before you accept the selected targets with Enter.
Selecting a missing CLI configures its paths; CLI installation/login remain separate.

For scripts, keep explicit `--harness` values or use `--non-interactive`:

```sh
agent-config-one-shot install --harness claude,copilot
agent-config-one-shot install --non-interactive
agent-config-one-shot plan --interactive --harness claude
```

`--interactive` forces the checklist, with explicit IDs as its initial selection.
It requires terminal input/output. `--json` stays headless and cannot be combined
with `--interactive`. Terminals smaller than 44 columns × 10 rows can be resized
or cancelled; selection does not proceed until there is enough room.

## Commands

| Command | What it does |
| --- | --- |
| `list` | Show supported harnesses and executable detection |
| `plan` | Preview all changes without creating files |
| `install --dry-run` | Same preview through the installation entrypoint |
| `install` | Create references and skill adapters in a private transaction |
| `doctor` | Check managed wiring, link targets, and interrupted transactions |
| `restore` | Undo the managed wiring after checking for changed content |
| `recover` | Roll back an interrupted install or complete an interrupted restore |

`--json` provides machine-readable status and paths. `--home /path` and
`--root /path` select an isolated home and private control root. They can appear
before or after the command; they do not change the shell's `HOME`.

## Supported harnesses

| ID | Native personal skills | Shared root behavior |
| --- | --- | --- |
| `codex` | `~/.codex/skills` | Reads `~/.agents/skills` directly |
| `claude` | `~/.claude/skills` | Individual references |
| `cursor-cli` | `~/.cursor/skills` | Reads shared root directly |
| `copilot` | `~/.copilot/skills` | Reads shared root; metadata adapter when needed |
| `amp` | `~/.config/amp/skills` | Reads shared root directly |
| `cline` | `~/.cline/skills` | Reads shared root directly |
| `opencode` | `~/.config/opencode/skills` | Individual references |
| `devin` | `~/.config/devin/skills` | Individual references |
| `omp` | `~/.omp/agent/skills` | Individual references |
| `gjc` | Native root remains a real directory | Adds a managed custom skill directory |
| `command-code` | `~/.commandcode/skills` | Individual references |

An explicit `--skills-source` other than `~/.agents/skills` is connected to
the selected harnesses' personal roots. The tool does not redirect the shared
global root, so other harnesses do not acquire that additional source through
this installer. Their own compatibility discovery rules may still apply.

Provide one skill directory containing `SKILL.md`, or a directory whose
immediate children are skill directories. Existing same-name native content is
preserved: a different target or real directory is a conflict, not an overwrite.

## Ownership and layout

The default private control root is `~/.agents/agent-config-one-shot`:

```text
agent-config-one-shot/
├── harnesses/<id>/     # references to native config/authored paths
├── compat/copilot/    # metadata adapters, canonical procedure elsewhere
├── state.json         # owned operations and installation scope
├── journals/          # durable transaction progress
└── backups/           # private original bytes for necessary native edits
```

Native configuration stays authoritative. Central references follow both
in-place and atomic native saves; the installer does not copy config values
into its package. Only existing config files are referenced. Optional absent
files are reported and can be connected by rerunning after a CLI creates them.

Auth stores, sessions, caches, account identities, permission databases, and
installed plugins are not imported. Central native references **must not be
dereferenced into a portable export**. Private backups are local recovery
evidence, not distributable content. The software package contains only this
tool, its examples, and tests; no personal or third-party skill bundle ships.

### Two native exceptions

- GJC rejects a redirected native user skills root. It remains real, while an
  additive `skills.customDirectories` entry enables the managed directory.
  Round-trip YAML preserves unrelated settings and comments; the original
  file is backed up privately. If a user changes that file afterward, restore
  refuses to replace it. Aliased mappings/lists are detached before mutation.
  Reused YAML anchors or merge keys inside the owned skills mapping are refused
  without printing native values. This exception is the only native preference edit.
  A redirected config target's parent directory must already exist, and the native
  config must remain outside the control root.
- Copilot rejects array-valued `argument-hint` metadata. A small generated
  adapter normalizes the hint and references the original skill and resources.
  The shared skill body is not copied or rewritten.
  Rerun install to refresh changed source metadata; user-edited generated adapters
  remain protected, and `doctor` reports stale metadata.
  Refresh keeps the same canonical source path. A different same-name source is a
  conflict; use a distinct skill name or restore the existing wiring first.

## Repeatability and recovery

Run the same installation twice: matching links/files cause no duplicate
operations. A lock serializes writers. Conflicts are found before native
mutations. Each operation has an original and expected fingerprint, and a
durable journal is written before changes.

An installation error rolls back that transaction. If the process is killed,
`doctor` reports the pending journal and `recover` reconciles started operations
before rollback, or completes an interrupted restore. Edits made by another writer cause a refusal rather than a
clobber. Local journals are recovery records, not a security boundary against
someone who can edit your private control files.

GJC native writes retain displaced files in a private
`.agent-config-one-shot-<transaction>-<operation>` directory beside the config.
New bytes are published only to an absent path: a concurrent native save wins.
The native path can be briefly absent during this operation; interrupted moves
are recovered from the retained file. Writes through an already-open descriptor
remain in that retained file and are reported by `doctor` for manual reconciliation.
These local recovery copies survive restore and must not be exported.
The journal and backup directories must be real directories, not symlinks.

`restore` checks the entire installation first. It removes created links and
generated adapters, restores unchanged managed native edits, and retains new
user files/directories. Backups and control evidence are retained. A changed
native config or retargeted link blocks restore before it starts.

## Verification scope

`doctor` checks filesystem wiring only. It does not prove login, model access,
every skill invocation, or every MCP connection. Version-sensitive adapters
need native discovery/save probes when a harness changes its behavior.

For development and isolated CLI tests:

```sh
uv sync
uv run python -m unittest discover -s tests -v
uv build
```

The tests use disposable homes, never the developer's live agent configuration.
Public package publication and hosted CI require separate release evidence.

## References

- [Agent Skills format](https://agentskills.io/specification)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Claude skills](https://code.claude.com/docs/en/skills)
- [Cursor skills](https://cursor.com/docs/skills)
- [Copilot configuration](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference)
- [Amp skills](https://ampcode.com/docs/customize/skills)

Fork-specific GJC/OMP/Command Code/Devin paths follow the locally verified
adapters that motivated this project. Their provider credentials and schemas
are not generalized into a universal config format.

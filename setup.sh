#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'This checkout setup command requires uv. You can also install the wheel with pipx.' >&2
    exit 2
fi
exec uv run --locked --project "$project_dir" agent-config-one-shot install "$@"

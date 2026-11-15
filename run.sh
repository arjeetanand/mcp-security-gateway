#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_python=${MCP_DEMO_PYTHON:-"$project_dir/.venv/bin/python"}
if [ ! -x "$task_python" ]; then
  printf '%s\n' 'Python environment not found; create .venv or set MCP_DEMO_PYTHON.' >&2
  exit 1
fi
exec "$task_python" "$project_dir/scripts/run_local.py" "$@"

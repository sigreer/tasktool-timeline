#!/usr/bin/env bash
# One-off generation of a static timeline HTML file.
#
#   ./generate.sh <repo> [output.html] [-- extra timeline.py args]
#
# Examples:
#   ./generate.sh ~/Dev/sigreer/multistore
#   ./generate.sh ~/Dev/sigreer/multistore /tmp/ms.html --show-x
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${1:?usage: generate.sh <repo> [output.html] [extra args...]}"
out="${2:-timeline.html}"
shift || true; shift || true
PYTHONPATH="$here" python3 "$here/timeline/timeline.py" --repo "$repo" -o "$out" "$@"

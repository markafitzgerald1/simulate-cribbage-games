#!/usr/bin/env bash
# Compare the complete uploaded asset set from a release API response on stdin.
set -euo pipefail

manifest="$(cat -- "$1")"
jq -e --arg manifest "$manifest" '
  ($manifest | split("\n") | map(select(length > 0) | split("  ") |
    {digest: ("sha256:" + .[0]), name: .[1], state: "uploaded"}) | sort_by(.name)) as $expected
  | (.assets | map({digest, name, state}) | sort_by(.name)) == $expected
'

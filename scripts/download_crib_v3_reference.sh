#!/usr/bin/env bash
# Read only. Use the exact D9 prerelease ZIP after the rolling tag changes.
set -euo pipefail
gh release download crib-v4-shadow-41771033920 \
  --pattern v4-shadow-reference.zip --repo "$GITHUB_REPOSITORY"
echo "2174c22b9f391a0ade69bef00fec1dba98879d83b840588d9e12831b5108e779  v4-shadow-reference.zip" \
  | sha256sum --check --strict
unzip -q v4-shadow-reference.zip 'reference/*'

#!/usr/bin/env bash
# Run cargo on native/cfr for a pre-commit hook. rustup installs cargo in
# ~/.cargo/bin, which a hook's environment may not have on PATH.
set -euo pipefail
PATH="$HOME/.cargo/bin:$PATH"
cd "$(dirname "$0")/../native/cfr"
exec cargo "$@"

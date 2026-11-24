#!/usr/bin/env bash
# Run cargo on native/cfr for a pre-commit hook. rustup installs cargo in
# $CARGO_HOME/bin (~/.cargo/bin by default), which a hook's environment may
# not have on PATH.
set -euo pipefail
cargo_home=${CARGO_HOME:-}
# A relative CARGO_HOME would stop resolving after the `cd` below.
if [[ -n "$cargo_home" && "$cargo_home" != /* ]]; then
  cargo_home="$PWD/$cargo_home"
fi
# Cargo reads CARGO_HOME itself too, so pass on the absolute form.
if [[ -n "$cargo_home" ]]; then
  export CARGO_HOME="$cargo_home"
fi
# Prepend each folder on its own, so no empty entry (the current folder)
# enters PATH when HOME or PATH is unset.
if [[ -n "${HOME:-}" ]]; then
  PATH="$HOME/.cargo/bin${PATH:+:$PATH}"
fi
if [[ -n "$cargo_home" ]]; then
  PATH="$cargo_home/bin${PATH:+:$PATH}"
fi
# An exported CDPATH would let `cd` pick a same-named folder elsewhere.
CDPATH='' cd -- "$(dirname -- "$0")/../native/cfr"
exec cargo "$@"

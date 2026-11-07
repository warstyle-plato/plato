#!/bin/sh
set -eu
umask 077
mkdir -p /root/.codex/plato-state
chmod 700 /root/.codex /root/.codex/plato-state
exec python -m scripts.plato_dispatcher \
  --store-dir /root/.codex/plato-state \
  --workspace /workspace serve --poll-seconds 5

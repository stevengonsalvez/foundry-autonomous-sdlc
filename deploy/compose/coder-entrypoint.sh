#!/bin/sh
# The coder's Toolchain looks for agy at $HOME/.local/bin/agy before running the installer, and the job
# then copies it to /opt/agy (a no-op when the file there is the same size). Root's home is a tmpfs on a
# read-only root filesystem, so point that path at the baked-in, root-owned binary on every start.
set -eu
umask 077
mkdir -p "$HOME/.local/bin" "$STATE_DIR"
ln -sfn /opt/agy/bin/agy "$HOME/.local/bin/agy"
exec "$@"

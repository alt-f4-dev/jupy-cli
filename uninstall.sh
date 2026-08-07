#!/usr/bin/env bash
# Remove the user-level Linux/macOS jupy installation.

set -euo pipefail

data_home=${XDG_DATA_HOME:-$HOME/.local/share}
install_root=${JUPY_INSTALL_ROOT:-$data_home/jupy}
bin_dir=${JUPY_BIN_DIR:-$HOME/.local/bin}

rm -f -- "$bin_dir/jupy" "$bin_dir/jupip" "$bin_dir/jupyup"
rm -rf -- "$install_root"

printf 'Removed jupy from %s and %s\n' "$bin_dir" "$install_root"

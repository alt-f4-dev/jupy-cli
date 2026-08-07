#!/usr/bin/env bash
# Install jupy, jupip, and jupyup for the current Linux or macOS user.

set -euo pipefail

script_dir=$(cd -P -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)

data_home=${XDG_DATA_HOME:-$HOME/.local/share}
install_root=${JUPY_INSTALL_ROOT:-$data_home/jupy}
bin_dir=${JUPY_BIN_DIR:-$HOME/.local/bin}

backup_existing_command() {
    local path=$1
    local backup

    if [[ -e $path && ! -L $path ]]; then
        backup="$path.pre-shared-core"
        if [[ -e $backup ]]; then
            backup="$backup.$(date +%Y%m%d%H%M%S)"
        fi
        mv -- "$path" "$backup"
        printf 'Backed up existing command: %s -> %s\n' "$path" "$backup"
    elif [[ -L $path ]]; then
        rm -f -- "$path"
    fi
}

mkdir -p "$install_root/bin" "$install_root/core" "$bin_dir"

install -m 0644 "$script_dir/VERSION" "$install_root/VERSION"
install -m 0644 "$script_dir/core/jupy_core.py" "$install_root/core/jupy_core.py"
install -m 0644 "$script_dir/core/jupy_update.py" "$install_root/core/jupy_update.py"

install -m 0755 "$script_dir/bin/jupy" "$install_root/bin/jupy"
install -m 0755 "$script_dir/bin/jupip" "$install_root/bin/jupip"
install -m 0755 "$script_dir/bin/jupyup" "$install_root/bin/jupyup"

backup_existing_command "$bin_dir/jupy"
backup_existing_command "$bin_dir/jupip"
backup_existing_command "$bin_dir/jupyup"

ln -s "$install_root/bin/jupy" "$bin_dir/jupy"
ln -s "$install_root/bin/jupip" "$bin_dir/jupip"
ln -s "$install_root/bin/jupyup" "$bin_dir/jupyup"

printf 'Installed jupy core: %s\n' "$install_root/core/jupy_core.py"
printf 'Installed jupy updater: %s\n' "$install_root/core/jupy_update.py"
printf 'Installed commands: %s/jupy, %s/jupip, and %s/jupyup\n' "$bin_dir" "$bin_dir" "$bin_dir"

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
        printf '\n%s is not currently in PATH. Add this line to your shell profile:\n' "$bin_dir"
        printf 'export PATH="%s:$PATH"\n' "$bin_dir"
        ;;
esac

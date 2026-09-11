#!/bin/sh
# Install the BedJet systemd units for this checkout.
#
#   sudo ./install-systemd.sh [INSTALL_DIR]
#
# INSTALL_DIR is the directory that contains the hub/ and app/ directories; it
# defaults to the directory holding this script. The units are templates, so
# every __INSTALL_DIR__ placeholder is replaced with INSTALL_DIR before the unit
# is written to /etc/systemd/system.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
INSTALL_DIR=${1:-$SCRIPT_DIR}

if [ "$(id -u)" -ne 0 ]; then
    echo "error: must run as root (try: sudo $0 $*)" >&2
    exit 1
fi

if [ ! -d "$INSTALL_DIR/hub" ] || [ ! -d "$INSTALL_DIR/app" ]; then
    echo "error: $INSTALL_DIR does not look like a BedJet checkout (no hub/ or app/)" >&2
    exit 1
fi

# Escape the characters sed treats specially inside a replacement.
escaped=$(printf '%s' "$INSTALL_DIR" | sed 's/[&\\|]/\\&/g')

for template in bedjet-ble.service bedjet-hub.service app/bedjet-ui.service; do
    src="$SCRIPT_DIR/$template"
    [ -f "$src" ] || continue
    dest="/etc/systemd/system/$(basename "$template")"

    # Render to a temporary file and move it into place, so that an existing
    # symlink (for example one pointing back into this checkout) is replaced
    # rather than written through.
    sed "s|__INSTALL_DIR__|$escaped|g" "$src" > "$dest.new"
    chmod 644 "$dest.new"
    mv -f "$dest.new" "$dest"
    echo "installed $dest"
done

if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo
    echo "warning: $INSTALL_DIR/.env does not exist yet." >&2
    echo "         cp .env.example .env, then set BEDJET_ADDRESS to your BedJet's MAC." >&2
fi

systemctl daemon-reload
echo
echo "Next:"
echo "  systemctl enable --now bedjet-ble.service bedjet-hub.service"
echo "  systemctl enable --now bedjet-ui.service   # optional web UI"

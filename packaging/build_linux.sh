#!/usr/bin/env bash
# build_linux.sh — packages Dédalo for Linux.
#
# Outputs (in packaging/out/):
#   dedalo-<v>-linux-x86_64.tar.gz   portable (unzip and run)
#   dedalo_<v>_amd64.deb             Debian/Ubuntu (+ derivatives)
#   dedalo-<v>-x86_64.AppImage       any distro (single file)
#
# Usage:
#   bash packaging/build_linux.sh             # everything possible here
#   SOLO_BINARIO=1 bash packaging/build_linux.sh   # only the onedir + tar.gz
#
# Requires: python with the project and PyInstaller installed, tar, and for
# the .deb dpkg-deb (dpkg-dev package). The AppImage downloads appimagetool
# if it is not in PATH (can be skipped with SIN_APPIMAGE=1).
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

# Version from pyproject.toml (single source of truth).
VERSION="$("${PYTHON:-python3}" - <<'EOF'
import tomllib
from pathlib import Path
with open(Path("pyproject.toml"), "rb") as f:
    print(tomllib.load(f)["project"]["version"])
EOF
)"

OUT="$RAIZ/packaging/out"
NOMBRE="dedalo"
APPDIR="$OUT/AppDir"
STAGE="$OUT/deb"

echo "==> PyInstaller v$VERSION"
rm -rf "$OUT" build
"${PYTHON:-python3}" -m PyInstaller \
    --clean --noconfirm --distpath "$OUT" --workpath "$OUT/build" \
    packaging/"$NOMBRE".spec
APP="$OUT/$NOMBRE"
[ -x "$APP/$NOMBRE" ] || { echo "the binary was not produced in $APP" >&2; exit 1; }

# The desktop umask (0002) leaves everything group-writable and that leaks
# into the artifacts: dirs at 755 and files without the write bit, without
# touching the executables (find -type f ignores Qt's symlinks; chmod -R
# would fail on them). Applied at every stage: files created later (wrappers,
# .desktop) need it too.
normalizar() {
    find "$1" -type d -exec chmod 755 {} +
    find "$1" -type f -exec chmod go-w {} +
}
normalizar "$APP"

# ── 1) portable tar.gz ───────────────────────────────────────────────────────
# Structure: dedalo-<v>-linux-x86_64/
#               dedalo     ← launcher (./dedalo)
#               app/               ← onedir (exe + libs + data)
echo "==> portable tar.gz"
TAR="$OUT/$NOMBRE-$VERSION-linux-x86_64.tar.gz"
DESP="$OUT/portable/$NOMBRE-$VERSION-linux-x86_64"
rm -rf "$OUT/portable"
mkdir -p "$DESP"
cp -a "$APP" "$DESP/app"
cat > "$DESP/$NOMBRE" <<'EOF'
#!/usr/bin/env bash
# Launcher for the portable binary: it self-locates and installs nothing.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/app/dedalo" "$@"
EOF
chmod +x "$DESP/$NOMBRE"
normalizar "$DESP"
tar -czf "$TAR" -C "$OUT/portable" "$NOMBRE-$VERSION-linux-x86_64"
echo "    $TAR"

if [ "${SOLO_BINARIO:-0}" = "1" ]; then
    echo "==> SOLO_BINARIO=1: stop here."
    exit 0
fi

# ── 2) .deb ─────────────────────────────────────────────────────────────────
if command -v dpkg-deb >/dev/null 2>&1; then
    echo "==> .deb"
    rm -rf "$STAGE"
    mkdir -p "$STAGE/DEBIAN" \
             "$STAGE/opt/$NOMBRE" \
             "$STAGE/usr/bin" \
             "$STAGE/usr/share/applications" \
             "$STAGE/usr/share/icons/hicolor/scalable/apps"
    cp -a "$APP/." "$STAGE/opt/$NOMBRE/"
    cat > "$STAGE/usr/bin/$NOMBRE" <<EOF
#!/usr/bin/env bash
exec /opt/$NOMBRE/$NOMBRE "\$@"
EOF
    chmod 755 "$STAGE/usr/bin/$NOMBRE"
    cp dedalo/icono.svg \
       "$STAGE/usr/share/icons/hicolor/scalable/apps/$NOMBRE.svg"
    cat > "$STAGE/usr/share/applications/$NOMBRE.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Dédalo
Comment=Dédalo control panel
Exec=/usr/bin/$NOMBRE
Icon=$NOMBRE
Terminal=false
Categories=Development;Utility;
Keywords=dedalo;ia;
EOF
    # Qt goes inside the onedir; the system only provides GL/X and the tools
    # the framework invokes (bash and git), or the loop won't start.
    cat > "$STAGE/DEBIAN/control" <<EOF
Package: $NOMBRE
Version: $VERSION
Section: devel
Priority: optional
Architecture: amd64
Maintainer: BenReynor <benreynor@users.noreply.github.com>
Depends: bash, git, libgl1, libegl1, libxkbcommon-x11-0, libdbus-1-3, libfontconfig1, libglib2.0-0
Description: Dédalo control panel (PySide6 GUI)
 Desktop GUI to orchestrate AI agents (opencode/codex/claude)
 on a project, with a quality gate, reviews, metrics and alerts.
EOF
    normalizar "$STAGE"
    DEB="$OUT/${NOMBRE}_${VERSION}_amd64.deb"
    dpkg-deb --build --root-owner-group "$STAGE" "$DEB"
    echo "    $DEB"
else
    echo "==> no dpkg-deb: .deb skipped (install dpkg-dev)"
fi

# ── 3) AppImage ────────────────────────────────────────────────────────────
if [ "${SIN_APPIMAGE:-0}" = "1" ]; then
    echo "==> SIN_APPIMAGE=1: AppImage skipped"
    exit 0
fi

IMAGEN=""
for cand in "$(command -v appimagetool || true)" \
            "$HOME/.local/bin/appimagetool" "$OUT/appimagetool"; do
    [ -n "$cand" ] && [ -x "$cand" ] && IMAGEN="$cand" && break
done

if [ -z "$IMAGEN" ]; then
    echo "==> downloading appimagetool"
    URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    if curl -fsSL --retry 3 -o "$OUT/appimagetool" "$URL"; then
        chmod +x "$OUT/appimagetool"
        IMAGEN="$OUT/appimagetool"
    else
        echo "==> no network: AppImage skipped (or export SIN_APPIMAGE=1)"
        exit 0
    fi
fi

echo "==> AppImage"
rm -rf "$APPDIR"
mkdir -p "$APPDIR"
cp -a "$APP/." "$APPDIR/"
# `cp -a "$APP/."` dumps the onedir INSIDE AppDir (exe + _internal at the
# root), so AppRun points to the exe, not to a subfolder. The .desktop and the
# icon also go at the root (AppImage format requirement).
ln -sf "$NOMBRE" "$APPDIR/AppRun"
# PNG, not SVG: current appimagetool only takes .png/.xpm and wants .DirIcon.
cp packaging/icono.png "$APPDIR/$NOMBRE.png"
ln -sf "$NOMBRE.png" "$APPDIR/.DirIcon"
cat > "$APPDIR/$NOMBRE.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Dédalo
Comment=Dédalo control panel
Exec=$NOMBRE
Icon=$NOMBRE
Terminal=false
Categories=Development;Utility;
Keywords=dedalo;ia;
EOF
normalizar "$APPDIR"
ARCH=x86_64 "$IMAGEN" "$APPDIR" "$OUT/$NOMBRE-$VERSION-x86_64.AppImage" 2>/dev/null \
  || "$IMAGEN" --appimage-extract-and-run "$APPDIR" \
       "$OUT/$NOMBRE-$VERSION-x86_64.AppImage"
echo "    $OUT/$NOMBRE-$VERSION-x86_64.AppImage"

echo "==> done: $(ls -1 "$OUT" | grep -E '\.(deb|tar\.gz|AppImage)$' | tr '\n' ' ')"

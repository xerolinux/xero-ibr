#!/bin/sh
# Builds iBR as a self-contained AppImage (bundled Python, GTK4, glibc and libimobiledevice tools)
# with quick-sharun from https://github.com/pkgforge-dev/Anylinux-AppImages.
# Works in CI and on any Arch Linux host that has iBR's runtime dependencies installed.
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
ARCH=$(uname -m)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/ibr/__init__.py")
WORK=${WORK:-$ROOT/build/appimage}
QUICK_SHARUN_URL="https://raw.githubusercontent.com/pkgforge-dev/Anylinux-AppImages/refs/heads/main/useful-tools/quick-sharun.sh"

export ARCH VERSION
export APPDIR="$WORK/AppDir"
export OUTPATH="${OUTPATH:-$ROOT/dist}"
export OUTNAME="iBR-$VERSION-$ARCH.AppImage"
export ICON="$ROOT/ibr/data/com.techxero.ibr.svg"
export DESKTOP="$ROOT/data/com.techxero.ibr.desktop"
export MAIN_BIN=ibr
export DEPLOY_PYTHON=1
export DEPLOY_GTK=1
export GTK_FIX_NONSENSE=1
# Trace the real app so libraries GTK loads at runtime get bundled too.
export STRACE_BINARY=python3
export STRACE_FLAGS="-m ibr"
export PYTHONPATH="$ROOT"
if [ -n "${GITHUB_REPOSITORY:-}" ]; then
	export UPINFO="gh-releases-zsync|${GITHUB_REPOSITORY%/*}|${GITHUB_REPOSITORY#*/}|latest|*$ARCH.AppImage.zsync"
fi

rm -rf "$APPDIR"
mkdir -p "$WORK"
cd "$WORK"

QUICK_SHARUN=$(command -v quick-sharun || true)
if [ -z "$QUICK_SHARUN" ]; then
	QUICK_SHARUN="$WORK/quick-sharun"
	[ -x "$QUICK_SHARUN" ] || { curl -fsSL "$QUICK_SHARUN_URL" -o "$QUICK_SHARUN" && chmod +x "$QUICK_SHARUN"; }
fi

"$QUICK_SHARUN" \
	/usr/bin/python3 \
	/usr/bin/idevice_id \
	/usr/bin/ideviceinfo \
	/usr/bin/idevicepair \
	/usr/bin/idevicebackup2 \
	/usr/bin/afcclient \
	/usr/bin/idevicerestore \
	/usr/bin/irecovery \
	/usr/lib/libgtk-4.so* \
	/usr/lib/libsecret-1.so* \
	/usr/lib/libgirepository-2.0.so* \
	/usr/lib/libcairo-gobject.so*

SITE=$(find "$APPDIR" -type d -path '*/python3*/site-packages' -print -quit)
if [ -z "$SITE" ]; then
	echo "ERROR: bundled site-packages not found" >&2
	exit 1
fi
rm -rf "$SITE/ibr"
cp -r "$ROOT/ibr" "$SITE/ibr"
find "$SITE/ibr" -name '__pycache__' -prune -exec rm -rf {} +

cat > "$APPDIR/bin/ibr" <<'EOF'
#!/bin/sh
exec python3 -m ibr "$@"
EOF
chmod +x "$APPDIR/bin/ibr"

unset PYTHONPATH
"$QUICK_SHARUN" --make-appimage

if [ "${SKIP_TEST:-0}" != 1 ]; then
	"$QUICK_SHARUN" --test "$OUTPATH/$OUTNAME"
fi

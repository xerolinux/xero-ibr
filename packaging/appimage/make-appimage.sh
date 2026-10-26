#!/bin/sh
# Builds iBR as a self-contained AppImage (bundled Python, GTK4, glibc and libimobiledevice tools)
# with quick-sharun from https://github.com/pkgforge-dev/Anylinux-AppImages.
# iBR must be installed into the build system first: CI does that here as root; elsewhere run `makepkg -si`.
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
export ICON="$ROOT/ibr/data/icons/hicolor/scalable/apps/com.techxero.ibr.svg"
export DESKTOP="$ROOT/data/com.techxero.ibr.desktop"
export DEPLOY_PYTHON=1
export DEPLOY_GTK=1
export DEPLOY_GLYCIN=1
export DEPLOY_LIBHEIF=1
export GTK_FIX_NONSENSE=1
if [ -n "${GITHUB_REPOSITORY:-}" ]; then
	export UPINFO="gh-releases-zsync|${GITHUB_REPOSITORY%/*}|${GITHUB_REPOSITORY#*/}|latest|*$ARCH.AppImage.zsync"
fi

rm -rf "$APPDIR"
mkdir -p "$WORK"

if [ "$(id -u)" = 0 ]; then
	rm -rf "$WORK/wheel"
	python3 -m build --wheel --no-isolation --outdir "$WORK/wheel" "$ROOT"
	python3 -m installer --destdir=/ "$WORK"/wheel/*.whl
fi
if [ ! -x /usr/bin/ibr ]; then
	echo "ERROR: /usr/bin/ibr not found. Install iBR first (makepkg -si on Arch)." >&2
	exit 1
fi

cd "$WORK"
QUICK_SHARUN=$(command -v quick-sharun || true)
if [ -z "$QUICK_SHARUN" ]; then
	QUICK_SHARUN="$WORK/quick-sharun"
	[ -x "$QUICK_SHARUN" ] || { curl -fsSL "$QUICK_SHARUN_URL" -o "$QUICK_SHARUN" && chmod +x "$QUICK_SHARUN"; }
fi

# quick-sharun skips _hashlib (needed by pbkdf2_hmac) and does not scan site-packages for libraries; the
# backup browser decrypts with both.
"$QUICK_SHARUN" \
	/usr/bin/ibr \
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
	/usr/lib/libcairo-gobject.so* \
	/usr/lib/python3*/lib-dynload/_hashlib*.so \
	/usr/lib/python3*/site-packages/cryptography/hazmat/bindings/_rust.abi3.so

"$QUICK_SHARUN" --make-appimage

if [ "${SKIP_TEST:-0}" != 1 ]; then
	"$QUICK_SHARUN" --test "$OUTPATH/$OUTNAME"
fi

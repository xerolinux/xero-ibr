# Maintainer: DarkXero/XeroLinux <steve@techxero.com>
pkgname=ibr
pkgver=0.1.0
pkgrel=1
pkgdesc="iBackup/Restore: back up and restore iPhone and iPad on Linux (GTK4)"
arch=('any')
url="https://github.com/xerolinux/xero-ibr"
license=('MIT')
depends=(
  'gst-plugins-base'
  'gst-plugins-good'
  'gtk4'
  'libimobiledevice'
  'libsecret'
  'python'
  'python-cairo'
  'python-cryptography'
  'python-gobject'
  'usbmuxd'
)
makedepends=(
  'python-build'
  'python-installer'
  'python-setuptools'
  'python-wheel'
)
checkdepends=('python-pytest')
optdepends=(
  'libirecovery-git: detect devices in Recovery or DFU mode and leave Recovery mode (AUR)'
  'idevicerestore-git: update or restore iOS firmware (AUR, needs a 2024 or newer build for iOS 15+)'
  'org.freedesktop.secrets: remember backup passwords (gnome-keyring or kwallet)'
  'inter-font: the interface font the design uses'
  'gst-libav: play AAC, ALAC, H.264, HEVC and most other audio and video formats'
  'gst-plugins-bad: play AV1, DTS and more formats'
  'gst-plugins-ugly: play WMA, WMV, AC-3 and DVD video'
)
source=()

prepare() {
  rm -rf "$srcdir/$pkgname"
  mkdir -p "$srcdir/$pkgname"
  cp -r "$startdir"/{ibr,data,tests,pyproject.toml,README.md,LICENSE} "$srcdir/$pkgname/"
  find "$srcdir/$pkgname" -name '__pycache__' -prune -exec rm -rf {} +
}

build() {
  cd "$srcdir/$pkgname"
  python -m build --wheel --no-isolation
}

check() {
  cd "$srcdir/$pkgname"
  python -m pytest -q
}

package() {
  cd "$srcdir/$pkgname"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 data/com.techxero.ibr.desktop "$pkgdir/usr/share/applications/com.techxero.ibr.desktop"
  install -Dm644 ibr/data/icons/hicolor/scalable/apps/com.techxero.ibr.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/com.techxero.ibr.svg"
  install -Dm644 data/99-ibr.rules "$pkgdir/usr/lib/udev/rules.d/99-ibr.rules"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}

#!/bin/sh
# CI only: installs what iBR needs inside the Arch Linux build container.
set -eu

# Pinned to commits with iOS 15 through 26 support (Cryptex1, libtatsu signing). The 1.0.0 release from 2020
# cannot restore current iOS versions.
LIBIRECOVERY_COMMIT=93c117c29b1f6669bc4ceca8b84e1df06449fe33
IDEVICERESTORE_COMMIT=4b3e847e1d9a1210049a9e3f1d1caa38650c6617

pacman -Syu --noconfirm --needed \
	autoconf \
	automake \
	curl \
	git \
	gtk4 \
	libimobiledevice \
	libimobiledevice-glue \
	libsecret \
	libtatsu \
	libtool \
	libusbmuxd \
	libzip \
	openssl \
	pkgconf \
	python \
	python-cairo \
	python-build \
	python-gobject \
	python-installer \
	python-pytest \
	python-setuptools \
	python-wheel

build_from_git() {
	repo=$1
	commit=$2
	dir=$(mktemp -d)
	git clone --quiet "https://github.com/libimobiledevice/$repo.git" "$dir"
	git -C "$dir" checkout --quiet "$commit"
	(cd "$dir" && ./autogen.sh --prefix=/usr && make -j"$(nproc)" && make install)
	rm -rf "$dir"
}

build_from_git libirecovery "$LIBIRECOVERY_COMMIT"
build_from_git idevicerestore "$IDEVICERESTORE_COMMIT"
idevicerestore --help | grep -q -- '--plain-progress'
command -v irecovery

get-debloated-pkgs --add-common --prefer-nano

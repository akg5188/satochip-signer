################################################################################
#
# python-cffi
#
################################################################################

PYTHON_CFFI_VERSION = 1.17.1
PYTHON_CFFI_SOURCE = cffi-$(PYTHON_CFFI_VERSION).tar.gz
PYTHON_CFFI_SITE = https://files.pythonhosted.org/packages/fc/97/c783634659c2920c3fc70419e3af40972dbaf758daa229a7d6ea6135c90d
PYTHON_CFFI_SETUP_TYPE = setuptools
PYTHON_CFFI_DEPENDENCIES = host-pkgconf libffi
PYTHON_CFFI_LICENSE = MIT
PYTHON_CFFI_LICENSE_FILES = LICENSE

# cffi invokes pkg-config from setup.py, which breaks when Buildroot paths are
# non-ASCII. Reuse the ASCII aliases exported by build.sh when they exist.
PYTHON_CFFI_ENV = \
	PKG_CONFIG_ALLOW_SYSTEM_CFLAGS=1 \
	PKG_CONFIG_ALLOW_SYSTEM_LIBS=1 \
	PKG_CONFIG="$(if $(BR2_MESON_PKGCONF_HOST_BINARY),$(BR2_MESON_PKGCONF_HOST_BINARY),$(PKG_CONFIG_HOST_BINARY))" \
	PKG_CONFIG_SYSROOT_DIR="$(if $(BR2_MESON_STAGING_DIR),$(BR2_MESON_STAGING_DIR),$(STAGING_DIR))" \
	PKG_CONFIG_LIBDIR="$(if $(BR2_MESON_STAGING_DIR),$(BR2_MESON_STAGING_DIR),$(STAGING_DIR))/usr/lib/pkgconfig:$(if $(BR2_MESON_STAGING_DIR),$(BR2_MESON_STAGING_DIR),$(STAGING_DIR))/usr/share/pkgconfig"

# This host package uses pkg-config to find libffi, so we have to
# provide the proper hints for pkg-config to behave properly for host
# packages.
HOST_PYTHON_CFFI_ENV = \
	PKG_CONFIG_ALLOW_SYSTEM_CFLAGS=1 \
	PKG_CONFIG_ALLOW_SYSTEM_LIBS=1 \
	PKG_CONFIG="$(PKG_CONFIG_HOST_BINARY)" \
	PKG_CONFIG_SYSROOT_DIR="/" \
	PKG_CONFIG_LIBDIR="$(HOST_DIR)/lib/pkgconfig:$(HOST_DIR)/share/pkgconfig"
HOST_PYTHON_CFFI_DEPENDENCIES = host-pkgconf host-python-pycparser host-libffi

$(eval $(python-package))
$(eval $(host-python-package))

 ################################################################################
 #
 # python-mnemonic
 #
 ################################################################################

 PYTHON_MNEMONIC_VERSION = 0.20
 # The upstream project moved from trezor/mnemonic to trezor/python-mnemonic.
 # Use the current repository so clean rebuilds do not depend on a redirecting
 # legacy URL that can intermittently fail.
 PYTHON_MNEMONIC_SITE = $(call github,trezor,python-mnemonic,v$(PYTHON_MNEMONIC_VERSION))
 PYTHON_MNEMONIC_SETUP_TYPE = setuptools
 PYTHON_MNEMONIC_LICENSE = MIT

 
 $(eval $(python-package))

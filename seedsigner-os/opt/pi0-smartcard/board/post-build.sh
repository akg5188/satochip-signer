#!/bin/sh

set -u
set -e

# Clean up files included in skeleton not needed
rm -f ${TARGET_DIR}/etc/init.d/S01syslogd
rm -f ${TARGET_DIR}/etc/init.d/S02klogd
rm -f ${TARGET_DIR}/etc/init.d/S02sysctl
rm -f ${TARGET_DIR}/etc/init.d/S02mdev
rm -f ${TARGET_DIR}/etc/init.d/S20seedrng
rm -f ${TARGET_DIR}/etc/init.d/S40network
rm -f ${TARGET_DIR}/etc/init.d/S50pigpio

# Clean up test files included with numpy
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/tests
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/testing
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/core/tests
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/linalg/tests
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/f2py/tests
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/typing/tests

# Clean up files included in embit we don't need
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/embit/liquid

# Clean up tests/docs in other python included libs
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/pyzbar/tests
rm -rf ${TARGET_DIR}/usr/lib/python3.12/site-packages/qrcode/tests

# TP-only runtime does not use the broader SeedSigner data/tool bundles.
rm -rf ${TARGET_DIR}/opt/electronics
rm -rf ${TARGET_DIR}/opt/gpg_keys
rm -rf ${TARGET_DIR}/app-assets
rm -rf ${TARGET_DIR}/opt/tools
rm -f ${TARGET_DIR}/opt/AGENTS.md
rm -f ${TARGET_DIR}/opt/CHANGELOG.md
rm -f ${TARGET_DIR}/opt/CLAUDE.md
rm -f ${TARGET_DIR}/opt/requirements-desktop.txt
rm -f ${TARGET_DIR}/opt/setup.cfg
rm -f ${TARGET_DIR}/opt/setup.py

# Keep only the Chinese locale font set required by the current TP-only UI.
rm -f ${TARGET_DIR}/opt/src/seedsigner/resources/fonts/NotoSansJP-Regular.ttf
rm -f ${TARGET_DIR}/opt/src/seedsigner/resources/fonts/NotoSansKR-Regular.ttf
rm -f ${TARGET_DIR}/opt/src/seedsigner/resources/fonts/PlemolJPConsole-Regular-S.ttf
rm -f ${TARGET_DIR}/opt/src/seedsigner/resources/fonts/PlemolJPConsole-SemiBold-S.ttf

# Remove static resources that are only used by disabled tool/screensaver flows.
rm -rf ${TARGET_DIR}/opt/src/seedsigner/resources/diceware
rm -rf ${TARGET_DIR}/opt/src/seedsigner/resources/img/partners

# Clean up bigger python modules we don't need
rm -rf ${TARGET_DIR}/usr/lib/python3.12/turtle.pyc
rm -rf ${TARGET_DIR}/usr/lib/python3.12/pydoc.pyc
rm -rf ${TARGET_DIR}/usr/lib/python3.12/doctest.pyc
rm -rf ${TARGET_DIR}/usr/lib/python3.12/mailbox.pyc
rm -rf ${TARGET_DIR}/usr/lib/python3.12/zipfile.pyc
rm -rf ${TARGET_DIR}/usr/lib/python3.12/tarfile.pyc
rm -rf ${TARGET_DIR}/usr/lib/python3.12/pickletools.pyc
rm -rf ${TARGET_DIR}/usr/lib/python3.12/turtledemo
rm -rf ${TARGET_DIR}/usr/lib/python3.12/unittest
rm -rf ${TARGET_DIR}/usr/lib/python3.12/ensurepip

# Remove cryptography metadata that still builds non-deterministically as of 2025-11-11
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/cryptography-43.0.3.dist-info/RECORD

# ### Reproducibility experimentation
# ### Remove all pyc files I can seem to make reproducible and keep the py versions

rm -f ${TARGET_DIR}/usr/lib/python3.12/config-3.12-arm-linux-gnueabihf/Makefile
rm -f ${TARGET_DIR}/usr/lib/python3.12/multiprocessing/connection.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/json/decoder.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/core/_string_helpers.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/distutils/ccompiler.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/distutils/command/build_py.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/distutils/misc_util.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/distutils/system_info.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/f2py/auxfuncs.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/f2py/crackfortran.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/f2py/f2py2e.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/lib/_iotools.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/lib/npyio.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/lib/recfunctions.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/site-packages/numpy/lib/stride_tricks.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/traceback.pyc
rm -f ${TARGET_DIR}/usr/lib/python3.12/_sysconfigdata__linux_arm-linux-gnueabihf.pyc

find ${TARGET_DIR}/usr/lib/python3.12 -name '*.py' \
	-not -path "*/python3.12/multiprocessing/connection.py" \
	-not -path "*/python3.12/json/decoder.py" \
	-not -path "*/python3.12/site-packages/numpy/core/_string_helpers.py" \
	-not -path "*/python3.12/site-packages/numpy/distutils/ccompiler.py" \
	-not -path "*/python3.12/site-packages/numpy/distutils/command/build_py.py" \
	-not -path "*/python3.12/site-packages/numpy/distutils/misc_util.py" \
	-not -path "*/python3.12/site-packages/numpy/distutils/system_info.py" \
	-not -path "*/python3.12/site-packages/numpy/f2py/auxfuncs.py" \
	-not -path "*/python3.12/site-packages/numpy/f2py/crackfortran.py" \
	-not -path "*/python3.12/site-packages/numpy/f2py/f2py2e.py" \
	-not -path "*/python3.12/site-packages/numpy/lib/_iotools.py" \
	-not -path "*/python3.12/site-packages/numpy/lib/npyio.py" \
	-not -path "*/python3.12/site-packages/numpy/lib/recfunctions.py" \
	-not -path "*/python3.12/site-packages/numpy/lib/stride_tricks.py" \
	-not -path "*/python3.12/traceback.py" \
	-not -path "*/python3.12/_sysconfigdata__linux_arm-linux-gnueabihf.py" \
	-print0 | \
	xargs -0 --no-run-if-empty rm -f

find "${TARGET_DIR}" -name '.DS_Store' -print0 | xargs -0 --no-run-if-empty rm -f

# Add python byte code (aka __pycache__ directories) to increase boot and import module speed
SOURCE_DATE_EPOCH=1 PYTHONHASHSEED=0 ${HOST_DIR}/bin/python3.12 \
  "${BUILD_DIR}/python3-3.12.10/Lib/compileall.py" \
  -f --invalidation-mode=checked-hash "${TARGET_DIR}/opt/src"

# Keep the app runtime deterministic: always ship our application as plain .py
# sources so stale bytecode can never shadow freshly edited recovery logic.
find "${TARGET_DIR}/opt/src" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${TARGET_DIR}/opt/src" -type f -name '*.pyc' -delete

#!/bin/bash

set -o errexit -o pipefail
export FORCE_UNSAFE_CONFIGURE=1 # Allows buildroot/tar to run as root user in docker container

# global variables 
cur_dir_name=${PWD##*/}
cur_dir=$(pwd -L)
seedsigner_app_repo="https://github.com/3rditeration/seedsigner.git"
seedsigner_app_repo_branch="dev"
source_rootfs_overlay="./rootfs-overlay"

help()
{
  echo "Usage: build.sh [pi board] [options]
  
  Pi Board: (only one allowed)
  -a, --all         Build for all supported pi boards
      --pi0         Build for pi0 and pi0w
      --pi2         Build for pi2
      --pi02w       Build for pi02w and pi3
	  --pi02w-smartcard
      --pi4         Build for pi4 and pi4cmio
      --lafrite     Build for La Frite AML-S805X-AC
  
  Options:
  -h, --help           Display a help screen and quit
      --dev            Builds developer version of images
          --smartcard      Builds with smartcard support
      --no-clean       Leave previous build, target, and output files
      --debug-rootfs   Compress the built root filesystem into a tar.gz archive
      --skip-repo      Skip pulling repo, assume rootfs-overlay/opt is populated with app code
      --app-repo       Build image with not official seedsigner github repo
      --app-branch     Build image with repo branch other than default
      --app-commit-id  Build image with specific repo commit id
      --no-op          All other option ignored and script just hangs to keep container alive"
  exit 2
}

tail_endless() {
  echo "Running 'tail -f /dev/null' to keep script alive"
  tail -f /dev/null
  exit 0
}

install_local_translations() {
  local bundled_l10n_dir="${source_rootfs_overlay}/app-assets/seedsigner-translations/l10n"
  local target_l10n_dir="${rootfs_overlay}/opt/src/seedsigner/resources/seedsigner-translations/l10n"

  if [ ! -d "${bundled_l10n_dir}" ]; then
    echo "Bundled translation catalog not found, skipping localization assets"
    return 0
  fi

  mkdir -p "$(dirname "${target_l10n_dir}")"
  rm -rf "${target_l10n_dir}"
  cp -a "${bundled_l10n_dir}" "${target_l10n_dir}"
}

install_default_settings() {
  local settings_template="${source_rootfs_overlay}/default-settings.json"
  local settings_target="${rootfs_overlay}/opt/src/settings.json"

  if [ ! -f "${settings_template}" ] || [ ! -d "${rootfs_overlay}/opt/src" ]; then
    return 0
  fi

  cp "${settings_template}" "${settings_target}"
}

compile_app_translations() {
  local l10n_dir="${rootfs_overlay}/opt/src/seedsigner/resources/seedsigner-translations/l10n"
  local venv_dir=".translation-venv"
  local use_venv=0

  if [ ! -f "${rootfs_overlay}/opt/setup.py" ]; then
    echo "SeedSigner app tree not found, skipping translation compile"
    return 0
  fi

  if ! python3 -c "import babel" >/dev/null 2>&1; then
    # Create a local venv only if the host python does not already have Babel.
    if command -v virtualenv >/dev/null 2>&1; then
      virtualenv "${venv_dir}"
    else
      python3 -m venv "${venv_dir}"
    fi
    # shellcheck disable=SC1091
    source "${venv_dir}/bin/activate"
    pip install babel || exit
    use_venv=1
  fi

  cd "${rootfs_overlay}/opt"

  if [ -d "${l10n_dir}" ]; then
    find "${l10n_dir}" -name '*.mo' -delete
    python3 setup.py compile_catalog || exit
  else
    echo "Translation catalog directory not found, skipping compile_catalog"
  fi

  cd -
  if [ "${use_venv}" = "1" ]; then
    deactivate
  fi
}

prune_app_repo() {
  # Delete unnecessary files to save space
  # folders
  rm -rf ${rootfs_overlay}/opt/.github
  rm -rf ${rootfs_overlay}/opt/docker
  rm -rf ${rootfs_overlay}/opt/docs
  rm -rf ${rootfs_overlay}/opt/enclosures
  rm -rf ${rootfs_overlay}/opt/l10n
  rm -rf ${rootfs_overlay}/opt/seedsigner-screenshots
  rm -rf ${rootfs_overlay}/opt/src/seedsigner/resources/seedsigner-translations/.git*
  rm -rf ${rootfs_overlay}/opt/tests
  #rm -rf ${rootfs_overlay}/opt/tools
  rm -rf ${rootfs_overlay}/opt/.git*
  rm -rf ${rootfs_overlay}/opt/docker-compose.yml
  rm -rf ${rootfs_overlay}/opt/LICENSE.md
  rm -rf ${rootfs_overlay}/opt/MANIFEST.in
  rm -rf ${rootfs_overlay}/opt/pyproject.toml
  rm -rf ${rootfs_overlay}/opt/README.md
  rm -rf ${rootfs_overlay}/opt/requirements-raspi.txt
  rm -rf ${rootfs_overlay}/opt/requirements.txt
  rm -rf ${rootfs_overlay}/opt/seedsigner_pubkey.gpg
  rm -rf ${rootfs_overlay}/opt/src/seedsigner/resources/seedsigner-translations/LICENSE
  rm -rf ${rootfs_overlay}/opt/src/seedsigner/resources/seedsigner-translations/README.md
  rm -rf ${rootfs_overlay}/opt/src/seedsigner/resources/seedsigner-translations/l10n/**/**/*.po
}

prepare_app_overlay() {
  install_local_translations
  install_default_settings
  compile_app_translations
  prune_app_repo
}

write_runtime_integrity_manifest() {
  local repo_root script_path manifest_target build_commit_time repo_head build_time_utc repo_commit_epoch

  repo_root="$(cd "${cur_dir}/../.." && pwd -L)"
  script_path="${repo_root}/scripts/write_runtime_firmware_manifest.py"
  manifest_target="${rootfs_overlay}/opt/src/seedsigner/resources/offline-signer-firmware-integrity.json"

  if [ ! -f "${script_path}" ]; then
    echo "Integrity manifest generator not found, skipping firmware self-check manifest"
    return 0
  fi

  mkdir -p "$(dirname "${manifest_target}")"
  build_commit_time=""
  if [ -f "${rootfs_overlay}/opt/src/.build_commit_time" ]; then
    build_commit_time="$(cat "${rootfs_overlay}/opt/src/.build_commit_time")"
  fi
  repo_head="$(git -C "${repo_root}" rev-parse HEAD 2>/dev/null || echo unknown)"
  repo_commit_epoch="$(git -C "${repo_root}" show -s --format=%ct "${repo_head}" 2>/dev/null || true)"
  if [ -n "${repo_commit_epoch}" ]; then
    build_time_utc="$(date -u -d "@${repo_commit_epoch}" '+%Y-%m-%dT%H:%M:%SZ')"
  else
    build_time_utc=""
  fi

  python3 "${script_path}" \
    --repo-root "${repo_root}" \
    --overlay-root "${rootfs_overlay}" \
    --output "${manifest_target}" \
    --repo-head "${repo_head}" \
    --build-commit-time "${build_commit_time}" \
    --build-time-utc "${build_time_utc}"
}

download_app_repo() {
  # remove previous opt seedsigner app repo code if it already exists
  rm -fr ${rootfs_overlay}/opt/
  
  # Download SeedSigner from GitHub and put into rootfs
  
  # check for custom app branch or custom commit. Custom commit takes priority over branch name
  if ! [ -z ${seedsigner_app_repo_commit_id} ]; then
    echo "cloning repo ${seedsigner_app_repo} with commit id ${seedsigner_app_repo_commit_id}"
    git clone --recurse-submodules "${seedsigner_app_repo}" "${rootfs_overlay}/opt/" || exit
    cd ${rootfs_overlay}/opt/
    git reset --hard "${seedsigner_app_repo_commit_id}"
    cd -
  else
    echo "cloning repo ${seedsigner_app_repo} with branch ${seedsigner_app_repo_branch}"
    git clone --recurse-submodules --depth 1 -b "${seedsigner_app_repo_branch}" "${seedsigner_app_repo}" "${rootfs_overlay}/opt/" || exit
  fi

  repo_commit_epoch=$(git -C "${rootfs_overlay}/opt" log -1 --format=%ct 2>/dev/null || true)
  if [ -n "$repo_commit_epoch" ]; then
    repo_commit_time=$(date -u -d "@${repo_commit_epoch}" "+%Y-%m-%d %H:%M")
    echo "${repo_commit_time}" > "${rootfs_overlay}/opt/src/.build_commit_time"
  fi

  prepare_app_overlay
}

build_image() {
  # arguments: $1 - config name, $2 clean/no-clean - allows for, $3 skip-repo

  # Variables
  config_name="${1:-pi0}"
  config_dir="./${config_name}"
  rootfs_overlay="${source_rootfs_overlay}"
  config_file="${config_dir}/configs/pi0"
  build_dir="${TP_BUILD_DIR:-${cur_dir}/../output}"
  image_dir="${TP_IMAGE_DIR:-${cur_dir}/../images}"
  generated_rootfs_overlay="${build_dir}/generated-rootfs-overlay"

  if [ ! -d "${config_dir}" ]; then
    # config does not exists
    echo "config ${config_name} not found"
    exit 1
  fi
  
  if [ "${2}" != "no-clean" ]; then
  
    # remove previous build dir
    rm -rf "${build_dir}"
    mkdir -p "${build_dir}"
    
  fi

  if [ "${3}" = "skip-repo" ]; then
    rm -rf "${generated_rootfs_overlay}"
    mkdir -p "${generated_rootfs_overlay}"
    rsync -a --delete "${source_rootfs_overlay}/" "${generated_rootfs_overlay}/"
    rootfs_overlay="${generated_rootfs_overlay}"
  fi
  
  if [ "${3}" != "skip-repo" ]; then
    download_app_repo
  else
    install_default_settings
  fi

  if [ "${3}" = "skip-repo" ]; then
    write_runtime_integrity_manifest
  fi

  # Setup external tree
  #make BR2_EXTERNAL="../${config_dir}/" O="${build_dir}" -C ./buildroot/ #2> /dev/null > /dev/null

  PATH="/usr/lib/ccache:${PATH}" make BR2_EXTERNAL="../${config_dir}/" O="${build_dir}" -C ./buildroot/ ${config_name}_defconfig
  if [ -f "${build_dir}/.config" ]; then
    python3 - "${build_dir}/.config" "${rootfs_overlay}" "${3}" "${BR2_JLEVEL:-}" <<'EOF'
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
overlay_path = Path(sys.argv[2]).resolve().as_posix()
skip_repo = sys.argv[3] == "skip-repo"
br2_jlevel = sys.argv[4]
content = config_path.read_text(encoding="utf-8")
updated = content

if skip_repo:
    updated = re.sub(
        r'^BR2_ROOTFS_OVERLAY=".*"$',
        f'BR2_ROOTFS_OVERLAY="{overlay_path}"',
        updated,
        flags=re.MULTILINE,
    )
    if updated == content:
        raise SystemExit("BR2_ROOTFS_OVERLAY not found in generated Buildroot config")

if br2_jlevel:
    if not br2_jlevel.isdigit():
        raise SystemExit(f"Invalid BR2_JLEVEL override: {br2_jlevel}")
    if re.search(r"^BR2_JLEVEL=.*$", updated, flags=re.MULTILINE):
        updated = re.sub(
            r"^BR2_JLEVEL=.*$",
            f"BR2_JLEVEL={br2_jlevel}",
            updated,
            flags=re.MULTILINE,
        )
    else:
        updated = updated.rstrip() + f"\nBR2_JLEVEL={br2_jlevel}\n"

if updated != content:
    config_path.write_text(updated, encoding="utf-8")
EOF
  fi

  # Meson/pkgconf breaks on non-ASCII sysroot paths. Expose stable ASCII aliases
  # so generated cross-compilation files never point at the Chinese workspace path.
  # Query Buildroot for the actual host/sysroot directories because recent
  # Buildroot layouts do not always expose the legacy output/staging path.
  meson_vars_output=$(
    env PATH="/usr/lib/ccache:${PATH}" make -s BR2_EXTERNAL="../${config_dir}/" O="${build_dir}" -C ./buildroot/ \
      printvars VARS='HOST_DIR STAGING_DIR' QUOTED_VARS=YES 2>/dev/null || true
  )
  meson_host_dir=$(printf '%s\n' "${meson_vars_output}" | sed -n "s/^HOST_DIR='\(.*\)'$/\1/p" | head -n1)
  meson_staging_dir=$(printf '%s\n' "${meson_vars_output}" | sed -n "s/^STAGING_DIR='\(.*\)'$/\1/p" | head -n1)
  if [ -z "${meson_host_dir}" ]; then
    meson_host_dir="${build_dir}/host"
  fi
  if [ -z "${meson_staging_dir}" ]; then
    meson_staging_dir=$(
      find "${build_dir}/host" -type d -path '*/sysroot/usr/lib/pkgconfig' 2>/dev/null \
        | sed 's#/usr/lib/pkgconfig$##' \
        | head -n1
    )
  fi
  if [ -z "${meson_staging_dir}" ] && [ -L "${build_dir}/staging" ]; then
    meson_staging_dir="$(readlink -f "${build_dir}/staging" 2>/dev/null || true)"
  fi
  if [ -z "${meson_staging_dir}" ]; then
    meson_staging_dir="${build_dir}/staging"
  fi
  meson_alias_base="/tmp/seedsigner-meson-${config_name}"
  meson_host_alias="${meson_alias_base}-host"
  meson_staging_alias="${meson_alias_base}-staging"
  meson_pkgconf_wrapper="${meson_alias_base}-pkgconf"
  ln -sfn "${meson_host_dir}" "${meson_host_alias}"
  ln -sfn "${meson_staging_dir}" "${meson_staging_alias}"
  cat > "${meson_pkgconf_wrapper}" <<'EOF'
#!/usr/bin/env python3
import os
import subprocess
import sys


def escaped_pkgconf_path(path: str) -> bytes:
    out = bytearray()
    for b in path.encode("utf-8"):
        if b < 128:
            out.append(b)
        else:
            out.append(0x5C)
            out.append(b)
    return bytes(out)


real_pkgconf = os.environ["TP_REAL_PKGCONF"]
real_host = os.environ["TP_REAL_HOST_DIR"]
alias_host = os.environ["TP_ALIAS_HOST_DIR"]
real_staging = os.environ["TP_REAL_STAGING_DIR"]
alias_staging = os.environ["TP_ALIAS_STAGING_DIR"]
env = os.environ.copy()
env["PKG_CONFIG_SYSROOT_DIR"] = real_staging
env["PKG_CONFIG_LIBDIR"] = (
    f"{real_staging}/usr/lib/pkgconfig:{real_staging}/usr/share/pkgconfig"
)
proc = subprocess.run(
    [real_pkgconf, *sys.argv[1:]],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
)
stdout = proc.stdout
for real_path, alias_path in (
    (real_host, alias_host),
    (real_staging, alias_staging),
):
    stdout = stdout.replace(real_path.encode("utf-8"), alias_path.encode("utf-8"))
    stdout = stdout.replace(escaped_pkgconf_path(real_path), alias_path.encode("utf-8"))

sys.stdout.buffer.write(stdout)
sys.stderr.buffer.write(proc.stderr)
sys.exit(proc.returncode)
EOF
  chmod +x "${meson_pkgconf_wrapper}"
  export TP_REAL_PKGCONF="${meson_host_dir}/bin/pkgconf"
  export TP_REAL_HOST_DIR="${meson_host_dir}"
  export TP_ALIAS_HOST_DIR="${meson_host_alias}"
  export TP_REAL_STAGING_DIR="${meson_staging_dir}"
  export TP_ALIAS_STAGING_DIR="${meson_staging_alias}"
  export BR2_MESON_HOST_DIR="${meson_host_alias}"
  export BR2_MESON_STAGING_DIR="${meson_staging_alias}"
  export BR2_MESON_PKGCONF_HOST_BINARY="${meson_pkgconf_wrapper}"

  cd "${build_dir}"
  PATH="/usr/lib/ccache:${PATH}" make
  
  # if successful, mv seedsigner_os.img image to /images
  # rename to image to include branch name and config name, then compress
  
  # Sanitize branch name so that it is safe for filenames
  sanitized_branch=$(echo "${seedsigner_app_repo_branch}" | tr -c 'A-Za-z0-9_.-' '_')
  seedsigner_os_image_output="${image_dir}/seedsigner_os.${sanitized_branch}.${config_name}.img"
  if ! [ -z ${seedsigner_app_repo_commit_id} ]; then
    # use commit id instead of branch name if it is set
    seedsigner_os_image_output="${image_dir}/seedsigner_os.${seedsigner_app_repo_commit_id}.${config_name}.img"
  fi
  
  if [ -f "${build_dir}/images/seedsigner_os.img" ] && [ -d "${image_dir}" ]; then
    mv -f "${build_dir}/images/seedsigner_os.img" "${seedsigner_os_image_output}"
    # Set a fixed timestamp to keep reproducible metadata on the raw image
    touch -d '2025-07-01 00:00:00' "${seedsigner_os_image_output}"

    # Output checksum for the raw image
    sha256sum "${seedsigner_os_image_output}"
  fi

  if [ -n "${DEBUG_ROOTFS}" ] && [ -d "${build_dir}/target" ]; then
    rootfs_tar_output="${image_dir}/seedsigner_os_rootfs.${sanitized_branch}.${config_name}.tar.gz"
    if ! [ -z ${seedsigner_app_repo_commit_id} ]; then
      rootfs_tar_output="${image_dir}/seedsigner_os_rootfs.${seedsigner_app_repo_commit_id}.${config_name}.tar.gz"
    fi

    tar -C "${build_dir}" -czf "${rootfs_tar_output}" target
    touch -d '2025-07-01 00:00:00' "${rootfs_tar_output}"
    sha256sum "${rootfs_tar_output}"
  fi
  
  cd - > /dev/null # return to previous working directory quietly
}

###
### Gather Arguments passed into build.sh script
###

VALID_ARGUMENTS=$# # Returns the count of arguments that are in short or long options

if [ "$VALID_ARGUMENTS" -eq 0 ]; then
  help
fi

PARAMS=""
ARCH_CNT=0
while (( "$#" )); do
  case "$1" in
  -a|--all)
    ALL_FLAG=0; ((ARCH_CNT=ARCH_CNT+1)); shift
    ;;
  -h|--help)
    HELP_FLAG=0; shift
    ;;
  --pi0)
    PI0_FLAG=0; ((ARCH_CNT=ARCH_CNT+1)); shift
    ;;
  --pi2)
    PI2_FLAG=0; ((ARCH_CNT=ARCH_CNT+1)); shift
    ;;
  --pi02w)
    PI02W_FLAG=0; ((ARCH_CNT=ARCH_CNT+1)); shift
    ;;
  --pi4)
    PI4_FLAG=0; ((ARCH_CNT=ARCH_CNT+1)); shift
    ;;
  --lafrite)
    LAFRITE_FLAG=0; ((ARCH_CNT=ARCH_CNT+1)); shift
    ;;
  --no-clean)
    NOCLEAN=0; shift
    ;;
  --skip-repo)
    SKIPREPO=0; shift
    ;;
  --no-op)
    NO_OP=0; shift
    ;;
  --dev)
    DEVBUILD=0; shift
    ;;
  --smartcard)
    SMARTCARD=0; shift
    ;;
  --debug-rootfs)
    DEBUG_ROOTFS=0; shift
    ;;
  --app-repo=*)
    APP_REPO=$(echo "${1}" | cut -d "=" -f2-); shift
    ;;
  --app-branch=*)
    APP_BRANCH=$(echo "${1}" | cut -d "=" -f2-); shift
    ;;
  --app-commit-id=*)
    APP_COMMITID=$(echo "${1}" | cut -d "=" -f2-); shift
    ;;
  -*|--*=) # unsupported flags
    echo "Error: Unsupported flag $1" >&2
    help
    exit 1
    ;;
  *) # unsupported flags
    echo "Error: Unsupported argument $1" >&2
    help
    exit 1
    ;;
  esac
done

# When no arguments, display help
if ! [ -z ${HELP_FLAG} ]; then
  help
fi

# Only allow 1 architecture related argument flag
if [ $ARCH_CNT -gt 1 ]; then
  echo "Invalid number of architecture arguments" >&2
  exit 3
fi

# if no-op then hang endlessly
if ! [ -z $NO_OP ]; then
  tail_endless
  exit 0
fi

# Check for --no-clean argument to pass clean/no-clean to build_image function
if [ -z $NOCLEAN ]; then
  CLEAN_ARG="clean"
else
  CLEAN_ARG="no-clean"
fi

# Check for --no-clean argument to pass clean/no-clean to build_image function
if ! [ -z $SKIPREPO ]; then
  SKIPREPO_ARG="skip-repo"
else
  SKIPREPO_ARG="no-skip-repo"
fi

echo $SKIPREPO_ARG

# Check for --dev argument to pass to build_image function
DEVARG=""
if ! [ -z $DEVBUILD ]; then
  DEVARG="-dev"
fi

# Check for --dev argument to pass to build_image function
SMARTCARDARG=""
if ! [ -z $SMARTCARD ]; then
  SMARTCARDARG="-smartcard"
fi

# check for custom app repo
if ! [ -z ${APP_REPO} ]; then
  seedsigner_app_repo="${APP_REPO}"
fi

# check for custom app branch
if ! [ -z ${APP_BRANCH} ]; then
  seedsigner_app_repo_branch="${APP_BRANCH}"
fi

# check for custom app branch
if ! [ -z ${APP_COMMITID} ]; then
  seedsigner_app_repo_commit_id="${APP_COMMITID}"
fi

###
### Run build_image function based on input arguments
###

# Build All Architectures
if ! [ -z ${ALL_FLAG} ]; then
  build_image "pi0${SMARTCARDARG}${DEVARG}" "clean" "${SKIPREPO_ARG}"
  build_image "pi02w${SMARTCARDARG}${DEVARG}" "clean" "skip-repo"
  build_image "pi2${SMARTCARDARG}${DEVARG}" "clean" "skip-repo"
  build_image "pi4${SMARTCARDARG}${DEVARG}" "clean" "skip-repo"
fi

# Build only for pi0, pi0w, and pi1
if ! [ -z ${PI0_FLAG} ]; then
  build_image "pi0${SMARTCARDARG}${DEVARG}" "${CLEAN_ARG}" "${SKIPREPO_ARG}"
fi

# Build only for pi2
if ! [ -z ${PI2_FLAG} ]; then
  build_image "pi2${SMARTCARDARG}${DEVARG}" "${CLEAN_ARG}" "${SKIPREPO_ARG}"
fi

# build for pi02w
if ! [ -z ${PI02W_FLAG} ]; then
  build_image "pi02w${SMARTCARDARG}${DEVARG}" "${CLEAN_ARG}" "${SKIPREPO_ARG}"
fi

# build for pi4
if ! [ -z ${PI4_FLAG} ]; then
  build_image "pi4${SMARTCARDARG}${DEVARG}" "${CLEAN_ARG}" "${SKIPREPO_ARG}"
fi

# build for La Frite AML-S805X-AC
if ! [ -z ${LAFRITE_FLAG} ]; then
  build_image "lafrite${SMARTCARDARG}${DEVARG}" "${CLEAN_ARG}" "${SKIPREPO_ARG}"
fi

exit 0

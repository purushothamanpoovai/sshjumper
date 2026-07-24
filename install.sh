#!/usr/bin/env bash
# SSHJumper one-click installer
# Usage: ./install.sh
# After install, activate in the current terminal: source ~/.sshjumper.rc
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT

# Real user when invoked via sudo (bashrc / config under their home)
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  TARGET_USER="${SUDO_USER}"
  TARGET_HOME="$(getent passwd "${SUDO_USER}" | cut -d: -f6)"
elif [[ "$(id -u)" -eq 0 ]]; then
  TARGET_USER="$(stat -c '%U' "${ROOT}" 2>/dev/null || echo root)"
  if [[ "${TARGET_USER}" == "root" ]] && [[ -n "${HOME}" && "${HOME}" != "/root" ]]; then
    TARGET_HOME="${HOME}"
    TARGET_USER="$(stat -c '%U' "${HOME}" 2>/dev/null || echo root)"
  else
    TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
  fi
else
  TARGET_USER="$(id -un)"
  TARGET_HOME="${HOME}"
fi
readonly TARGET_USER TARGET_HOME

BASHRC="${TARGET_HOME}/.bashrc"
SSHJUMPER_RC="${TARGET_HOME}/.sshjumper.rc"
CONFIG_DIR="${TARGET_HOME}/.ssh/sshjumper"
KEYS_DIR="${TARGET_HOME}/.ssh/ssh_keys"
CONFIG_FILE="${CONFIG_DIR}/sshjconfig.yml"
PASSWORD_FILE="${CONFIG_DIR}/passwords.yml"

MARKER_BEGIN="# >>> sshjumper begin >>>"
MARKER_END="# <<< sshjumper end <<<"
YES_TO_ALL=0

# ---------------------------------------------------------------------------
# Pretty status (apt-like realtime progress lines)
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'
  C_CYAN=$'\033[36m'
  C_BLUE=$'\033[34m'
else
  C_RESET= C_BOLD= C_DIM= C_GREEN= C_YELLOW= C_RED= C_CYAN= C_BLUE=
fi

step_n=0
step() {
  step_n=$((step_n + 1))
  printf '\n%s[%d]%s %s%s%s\n' \
    "${C_BOLD}${C_CYAN}" "${step_n}" "${C_RESET}" \
    "${C_BOLD}" "$*" "${C_RESET}"
}

info()  { printf '  %s*%s %s\n' "${C_BLUE}" "${C_RESET}" "$*"; }
ok()    { printf '  %s✓%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
warn()  { printf '  %s!%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*"; }
fail()  { printf '  %s✗%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2; }
header() {
  printf '\n%s══════════════════════════════════════════════%s\n' "${C_BOLD}" "${C_RESET}"
  printf '%s  SSHJumper installer%s\n' "${C_BOLD}" "${C_RESET}"
  printf '%s══════════════════════════════════════════════%s\n' "${C_BOLD}" "${C_RESET}"
}

die() {
  fail "$*"
  exit 1
}

run_as_target() {
  if [[ "$(id -un)" == "${TARGET_USER}" ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo -u "${TARGET_USER}" -- "$@"
  else
    "$@"
  fi
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    if ! sudo -n true 2>/dev/null; then
      info "sudo password may be required"
    fi
    sudo "$@"
  else
    return 127
  fi
}

# ---------------------------------------------------------------------------
# Platform detection (must run before any install action)
# ---------------------------------------------------------------------------
detect_platform() {
  OS_ID="unknown"
  OS_LIKE=""
  OS_VERSION=""
  OS_PRETTY="Unknown"
  PKG_MGR=""
  PKG_FAMILY="unknown"
  PKG_REFRESH=()
  PKG_INSTALL=()

  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_LIKE="${ID_LIKE:-}"
    OS_VERSION="${VERSION_ID:-}"
    OS_PRETTY="${PRETTY_NAME:-$OS_ID $OS_VERSION}"
  fi

  case "${OS_ID}" in
    ubuntu|debian|linuxmint|pop|elementary|raspbian)
      PKG_FAMILY="debian"
      ;;
    fedora|rhel|centos|rocky|almalinux|ol|amzn)
      PKG_FAMILY="rhel"
      ;;
    opensuse*|sles)
      PKG_FAMILY="suse"
      ;;
    arch|manjaro|endeavouros)
      PKG_FAMILY="arch"
      ;;
    *)
      if [[ " ${OS_LIKE} " == *" debian "* ]] || [[ " ${OS_LIKE} " == *" ubuntu "* ]]; then
        PKG_FAMILY="debian"
      elif [[ " ${OS_LIKE} " == *" rhel "* ]] || [[ " ${OS_LIKE} " == *" fedora "* ]] || [[ " ${OS_LIKE} " == *" centos "* ]]; then
        PKG_FAMILY="rhel"
      elif [[ " ${OS_LIKE} " == *" suse "* ]]; then
        PKG_FAMILY="suse"
      elif [[ " ${OS_LIKE} " == *" arch "* ]]; then
        PKG_FAMILY="arch"
      else
        PKG_FAMILY="unknown"
      fi
      ;;
  esac

  case "${PKG_FAMILY}" in
    debian)
      PKG_MGR="apt-get"
      PKG_REFRESH=(apt-get update)
      PKG_INSTALL=(apt-get install -y)
      PKG_PYTHON="python3"
      PKG_PIP="python3-pip"
      PKG_SSH="openssh-client"
      PKG_VENV="python3-venv"
      ;;
    rhel)
      if command -v dnf >/dev/null 2>&1; then
        PKG_MGR="dnf"
        PKG_REFRESH=()
        PKG_INSTALL=(dnf install -y)
      else
        PKG_MGR="yum"
        PKG_REFRESH=()
        PKG_INSTALL=(yum install -y)
      fi
      PKG_PYTHON="python3"
      PKG_PIP="python3-pip"
      PKG_SSH="openssh-clients"
      PKG_VENV="python3"
      ;;
    suse)
      PKG_MGR="zypper"
      PKG_REFRESH=(zypper refresh)
      PKG_INSTALL=(zypper install -y)
      PKG_PYTHON="python3"
      PKG_PIP="python3-pip"
      PKG_SSH="openssh"
      PKG_VENV="python3-venv"
      ;;
    arch)
      PKG_MGR="pacman"
      PKG_REFRESH=()
      PKG_INSTALL=(pacman -S --noconfirm --needed)
      PKG_PYTHON="python"
      PKG_PIP="python-pip"
      PKG_SSH="openssh"
      PKG_VENV="python"
      ;;
    *)
      PKG_MGR=""
      PKG_PYTHON="python3"
      PKG_PIP="python3-pip"
      PKG_SSH="openssh-client"
      PKG_VENV="python3-venv"
      ;;
  esac
}

print_platform_info() {
  step "Platform check"
  info "${OS_PRETTY} · $(uname -m) · ${TARGET_USER} · ${PKG_MGR:-manual}"
  info "Install : ${ROOT}"
  if [[ -z "${PKG_MGR}" ]]; then
    warn "Unknown distro — install system packages manually if needed"
  fi
}

# ---------------------------------------------------------------------------
# Confirmation: y = yes, a = yes to all, c = cancel
# ---------------------------------------------------------------------------
confirm() {
  local prompt="$1"
  if [[ "${YES_TO_ALL}" -eq 1 ]]; then
    info "${prompt} → yes (all)"
    return 0
  fi
  local reply
  while true; do
    printf '  %s?%s %s [%sy%s/%sa%s/%sc%s]: ' \
      "${C_YELLOW}" "${C_RESET}" "${prompt}" \
      "${C_GREEN}" "${C_RESET}" "${C_GREEN}" "${C_RESET}" "${C_RED}" "${C_RESET}"
    read -r reply || true
    case "${reply}" in
      y|Y|yes|YES)
        return 0
        ;;
      a|A|all|ALL|"yes to all"|"YES TO ALL")
        YES_TO_ALL=1
        return 0
        ;;
      c|C|cancel|CANCEL|n|N|no|NO)
        return 1
        ;;
      *)
        warn "Enter y (yes), a (yes to all), or c (cancel)"
        ;;
    esac
  done
}

pkg_install() {
  local packages=("$@")
  [[ ${#packages[@]} -eq 0 ]] && return 0

  local cmd=("${PKG_INSTALL[@]}" "${packages[@]}")
  info "Running: ${cmd[*]}"
  echo
  if ! run_privileged "${cmd[@]}"; then
    die "Failed to install: ${packages[*]} (try: sudo ./install.sh)"
  fi
  echo
}

pkg_refresh() {
  [[ ${#PKG_REFRESH[@]} -eq 0 ]] && return 0
  info "Refreshing package indexes: ${PKG_REFRESH[*]}"
  echo
  if ! run_privileged "${PKG_REFRESH[@]}"; then
    die "Failed to refresh package indexes (try: sudo ./install.sh)"
  fi
  echo
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

python_ok() {
  have_cmd python3 || return 1
  python3 - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
}

pip_ok() {
  have_cmd pip3 || python3 -m pip --version >/dev/null 2>&1
}

ssh_ok() { have_cmd ssh; }

# PyYAML + textual already present under vendor/
vendor_ready() {
  [[ -d "${ROOT}/vendor/textual" ]] || return 1
  [[ -d "${ROOT}/vendor/yaml" ]] && return 0
  compgen -G "${ROOT}/vendor/pyyaml"* >/dev/null
}

# ---------------------------------------------------------------------------
# Precheck + selective major-package install
# ---------------------------------------------------------------------------
precheck_and_install_system() {
  step "Check dependencies"

  local missing_items=()
  local need_pip=0

  if python_ok; then
    ok "Python $(python3 --version 2>&1 | awk '{print $2}')"
  else
    warn "Python 3.9+ missing"
    if [[ "${PKG_FAMILY}" == "debian" && -n "${PKG_VENV}" && "${PKG_VENV}" != "${PKG_PYTHON}" ]]; then
      missing_items+=("Python 3 (${PKG_PYTHON} + ${PKG_VENV})|${PKG_PYTHON} ${PKG_VENV}")
    else
      missing_items+=("Python 3 (${PKG_PYTHON})|${PKG_PYTHON}")
    fi
  fi

  if pip_ok; then
    ok "pip"
  else
    if vendor_ready; then
      ok "pip (optional — vendor already present)"
    else
      warn "pip missing"
      need_pip=1
      missing_items+=("pip (${PKG_PIP})|${PKG_PIP}")
    fi
  fi

  if ssh_ok; then
    ok "OpenSSH"
  else
    warn "OpenSSH missing"
    missing_items+=("OpenSSH client (${PKG_SSH})|${PKG_SSH}")
  fi

  if [[ ${#missing_items[@]} -eq 0 ]]; then
    return 0
  fi

  if [[ -z "${PKG_MGR}" ]]; then
    local labels=()
    local item
    for item in "${missing_items[@]}"; do
      labels+=("${item%%|*}")
    done
    die "Cannot auto-install on this platform. Install manually: ${labels[*]}"
  fi

  info "Install via ${PKG_MGR}  (y / a=all / c=cancel)"
  local to_install=()
  local item label pkgs pkg
  for item in "${missing_items[@]}"; do
    label="${item%%|*}"
    pkgs="${item#*|}"
    if confirm "Install ${label}"; then
      # shellcheck disable=SC2206
      for pkg in ${pkgs}; do
        to_install+=("$pkg")
      done
    else
      die "Installation cancelled by user (needed: ${label})"
    fi
  done

  local unique=() seen p
  for pkg in "${to_install[@]}"; do
    seen=0
    for p in "${unique[@]+"${unique[@]}"}"; do
      [[ "$p" == "$pkg" ]] && seen=1 && break
    done
    [[ $seen -eq 0 ]] && unique+=("$pkg")
  done

  [[ ${#unique[@]} -eq 0 ]] && return 0

  step "Install system packages"
  pkg_refresh
  pkg_install "${unique[@]}"

  python_ok || die "Python 3.9+ still missing after install"
  ssh_ok || die "ssh still missing after install"
  if [[ "${need_pip}" -eq 1 ]]; then
    pip_ok || die "pip still missing after install"
  fi
  ok "System packages installed"
}

# ---------------------------------------------------------------------------
# Python vendor deps (no per-package confirmation)
# ---------------------------------------------------------------------------
install_vendor_deps() {
  if vendor_ready && ! pip_ok; then
    ok "Python packages (vendor/)"
    return 0
  fi

  if ! pip_ok; then
    die "pip is required to install vendor deps (install ${PKG_PIP} then re-run)"
  fi

  run_as_target bash "${ROOT}/install-vendor.sh" >/dev/null
  ok "Python packages (vendor/)"
}

# ---------------------------------------------------------------------------
# Application files / permissions (quiet)
# ---------------------------------------------------------------------------
prepare_app() {
  chmod +x "${ROOT}/sshjumper" "${ROOT}/install.sh" "${ROOT}/install-vendor.sh" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Config directories + example copy
# ---------------------------------------------------------------------------
prepare_config() {
  run_as_target mkdir -p "${CONFIG_DIR}" "${KEYS_DIR}"

  if [[ ! -f "${CONFIG_FILE}" ]]; then
    if [[ -f "${ROOT}/configs/sshjconfig.example.yml" ]]; then
      run_as_target cp "${ROOT}/configs/sshjconfig.example.yml" "${CONFIG_FILE}"
      ok "Config created  ${CONFIG_FILE}"
    else
      run_as_target touch "${CONFIG_FILE}"
      ok "Config created  ${CONFIG_FILE}"
    fi
  else
    ok "Config ready    ${CONFIG_FILE}"
  fi

  if [[ ! -f "${PASSWORD_FILE}" ]]; then
    run_as_target bash -c "umask 077; printf '# SSHJumper passwords (optional)\\n{}\\n' > '${PASSWORD_FILE}'"
  fi

  if [[ "$(id -u)" -eq 0 && -n "${TARGET_USER}" ]]; then
    chown -R "${TARGET_USER}:" "${CONFIG_DIR}" "${KEYS_DIR}" 2>/dev/null || true
  fi

  ok "SSH keys dir   ${KEYS_DIR}"
}

# ---------------------------------------------------------------------------
# Shell RC: write ~/.sshjumper.rc and include it once from ~/.bashrc
# ---------------------------------------------------------------------------
write_sshjumper_rc() {
  # Note: do not use the `:` builtin idiom here — `:` is the sshjumper alias.
  local tmp
  tmp="$(mktemp)"
  cat > "${tmp}" <<EOF
# SSHJumper shell integration
# Generated by install.sh — safe to re-run installer (file is overwritten).
# Activate:  source ~/.sshjumper.rc

export SSHJUMPER_HOME="${ROOT}"
export PATH="\${PATH}:\${SSHJUMPER_HOME}"

export SSHJUMPERCONFIGFILE="\${SSHJUMPERCONFIGFILE:-\${HOME}/.ssh/sshjumper/sshjconfig.yml}"
export SSHJUMPERPASSWORDFILE="\${SSHJUMPERPASSWORDFILE:-\${HOME}/.ssh/sshjumper/passwords.yml}"
export SSHJUMPERSSHKEYS="\${SSHJUMPERSSHKEYS:-\${HOME}/.ssh/ssh_keys/}"

# Short alias:  : server_name
alias :='\$SSHJUMPER_HOME/sshjumper'

if [ -f "\${SSHJUMPER_HOME}/install/ssh-jumper-completion.rc" ]; then
  # shellcheck disable=SC1091
  . "\${SSHJUMPER_HOME}/install/ssh-jumper-completion.rc"
fi
EOF

  if [[ "$(id -un)" == "${TARGET_USER}" ]] || [[ "$(id -u)" -eq 0 ]]; then
    cat "${tmp}" > "${SSHJUMPER_RC}"
    [[ "$(id -u)" -eq 0 ]] && chown "${TARGET_USER}:" "${SSHJUMPER_RC}" 2>/dev/null || true
  else
    sudo -u "${TARGET_USER}" cp "${tmp}" "${SSHJUMPER_RC}"
  fi
  rm -f "${tmp}"

  # Keep a copy under the repo for reference / manual setups
  mkdir -p "${ROOT}/install"
  cp "${SSHJUMPER_RC}" "${ROOT}/install/sshjumper.rc" 2>/dev/null || true
}

ensure_bashrc_source() {
  if [[ ! -f "${BASHRC}" ]]; then
    run_as_target touch "${BASHRC}"
  fi

  local block_file out_file
  block_file="$(mktemp)"
  out_file="$(mktemp)"
  cat > "${block_file}" <<EOF
${MARKER_BEGIN}
# Managed by SSHJumper install.sh — do not duplicate this block
if [ -f "\${HOME}/.sshjumper.rc" ]; then
  # shellcheck disable=SC1091
  . "\${HOME}/.sshjumper.rc"
fi
${MARKER_END}
EOF

  if grep -qF "${MARKER_BEGIN}" "${BASHRC}" 2>/dev/null; then
    awk -v begin="${MARKER_BEGIN}" -v end="${MARKER_END}" -v bf="${block_file}" '
      $0 == begin {
        skip = 1
        while ((getline line < bf) > 0) print line
        close(bf)
        next
      }
      $0 == end { skip = 0; next }
      !skip { print }
    ' "${BASHRC}" > "${out_file}"
  else
    cat "${BASHRC}" > "${out_file}"
    printf '\n' >> "${out_file}"
    cat "${block_file}" >> "${out_file}"
  fi

  if [[ "$(id -un)" == "${TARGET_USER}" ]] || [[ "$(id -u)" -eq 0 ]]; then
    cat "${out_file}" > "${BASHRC}"
    [[ "$(id -u)" -eq 0 ]] && chown "${TARGET_USER}:" "${BASHRC}" 2>/dev/null || true
  else
    sudo -u "${TARGET_USER}" cp "${out_file}" "${BASHRC}"
  fi
  rm -f "${block_file}" "${out_file}"

  cat > "${ROOT}/install/alias.rc" <<'EOF'
# Deprecated: use ~/.sshjumper.rc (installed by ./install.sh)
# shellcheck disable=SC1090
[ -f "${HOME}/.sshjumper.rc" ] && . "${HOME}/.sshjumper.rc"
EOF

  ok "Added / Updated bashrc ssh jumper rc"
}

# ---------------------------------------------------------------------------
# Final instructions (short)
# ---------------------------------------------------------------------------
print_done() {
  echo
  ok "Install complete"
  echo
  printf '  Config  %s\n' "${CONFIG_FILE}"
  printf '  Keys    %s\n' "${KEYS_DIR}"
  echo
  printf '  %s: server_name%s   connect\n' "${C_CYAN}" "${C_RESET}"
  printf '  %s: --gui%s         TUI\n' "${C_CYAN}" "${C_RESET}"
  printf '  %s: --list%s        list\n' "${C_CYAN}" "${C_RESET}"
  echo
  info "Activate this session:  source ~/.sshjumper.rc"
  echo
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  header
  detect_platform
  print_platform_info

  if [[ -z "${PKG_MGR}" ]]; then
    warn "Continuing without auto package install"
  fi

  if ! confirm "Proceed with SSHJumper installation"; then
    die "Installation cancelled"
  fi

  echo
  precheck_and_install_system
  prepare_app
  install_vendor_deps
  prepare_config
  write_sshjumper_rc
  ensure_bashrc_source
  print_done
}

main "$@"

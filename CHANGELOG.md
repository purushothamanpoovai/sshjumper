# Changelog

## [2.2.0] - 2026-08-25

Extension framework, KeePass clipboard copy, and reserved config sections for globals/templates.

### Added
- `_global:` section for shared server defaults (e.g. `keep_alive: true` for all servers)
- `_hosts:` section for reusable hop templates (leading `_` = reserved / not a connectable server)
- Hop reference forms: `hop1: bastion` or `hop1: { use: bastion, port: 2222 }`
- Extension / plugin framework (`sshjumper_cli/extensions/`) with ON/OFF state in `~/.ssh/sshjumper/extensions.yml`
- Builtin extensions: `gui`, `passwords`, `keepass`, `clipboard`, `otp`, `terminal_title`
- KeePass lookup by server/entry name + clipboard copy (`pykeepass` and/or `keepassxc-cli`)
- CLI: `sshjumper ext list|enable|disable|path`
- Clear KeePass status lines: password copied / password not available / dependency missing

### Changed
- Prefer `_hosts:` / `_global:` over bare `hosts:` / `global:` (legacy aliases still work)
- Per-server keys override `_global` defaults (SSH `Host *` style)
- Pre/post-connect hooks run through the extension registry
- Interactive TUI (`--gui`) is gated by the `gui` extension (default on)
- Clipboard success is reported only after a verified native clipboard write

### Fixed
- `xclip` no longer hangs the connect path (it stays alive to own the selection; writes are timed out / detached)
- Missing clipboard tools report as dependency missing, not as password unavailable

### Notes
- Clipboard needs `xclip` (X11) or `wl-clipboard` (Wayland) plus a working `DISPLAY` / `WAYLAND_DISPLAY`
- KeePass DB path can be set under `extensions.yml` → `config.keepass.database`, or via env
- Unlock with `SSHJUMPERKEEPASSPASSWORD` (or an interactive prompt when available)
- `otp` ships as a stub; `passwords.yml` merge remains an enhancement
- `gui` requires Textual under `vendor/`; disable on headless CLI-only hosts

---

## [2.1.0] - 2026-07-24

### Added
- One-click `./install.sh` with OS detection (Ubuntu/Debian, Fedora/RHEL, openSUSE, Arch)
- Interactive package prompts for system deps: `y` / `a` (yes to all) / `c` (cancel)
- Shell integration file at `~/.sshjumper.rc` (sourced once from `~/.bashrc`)
- Checklist-style installer output for day-to-day users

### Changed
- Running with no arguments shows help (TUI is opt-in via `--gui`)
- Activate a session after install with `source ~/.sshjumper.rc` (not the full bashrc)
- Installer no longer prints internal paths or noisy prepare steps

### Fixed
- Bashrc include uses managed markers so re-running install does not duplicate `source` lines

---

## [2.0.0] - 2026-07-01

Python rewrite of the original Bash SSH jumper.

### Added
- `sshjumper_cli` package: YAML config, validation, ProxyJump `ssh_config` generation, OpenSSH execution
- Structured hop config (`hop1`, `hop2`, …) replacing the legacy hops string
- Interactive Textual TUI (`--gui`) with project/environment grouping and fuzzy filter
- Info modes: `-i` (hop path), `-ii` (full chain + generated config + command)
- Flags: `-l/--list`, `-c/--config`, `-q`, `-v`, `-X`, `--no-tty`
- Remote commands after `--` (e.g. `sshjumper host -- uptime`)
- Vendored deps via `./install-vendor.sh` (`vendor/`: PyYAML, Textual)
- Example config: `configs/sshjconfig.example.yml`
- Env vars: `SSHJUMPERCONFIGFILE`, `SSHJUMPERPASSWORDFILE`, `SSHJUMPERSSHKEYS`

### Changed
- Connections use system OpenSSH **ProxyJump** instead of nested `ssh` hops
- Relative identity keys resolve from `SSHJUMPERSSHKEYS` (default `~/.ssh/ssh_keys/`)

### Removed
- Bash implementation as the primary runtime (kept historically as `sshjumper_bkp`)

### Notes
- Extension placeholders retained but not fully ported: `copy`, `otp_secret`, `password`, `sudo`

---

## [1.x] - 2019-09-28 – 2023-08-30

Historical Bash implementation (`sshjumper_bkp`). Summarized newest-first.

### [1.8.0] - 2023-08-30
- Added `keep_alive` (`ServerAliveInterval` / `ServerAliveCountMax`)

### [1.7.0] - 2023-08-03
- Added `otp_secret` with OTP generation
- Password field drives clipboard copy (removed boolean copy flag)
- Terminal allocation on by default (`terminal: false` to disable)

### [1.6.0] - 2023-04-18
- Copy named password or OTP to clipboard (background `oathtool` refresh)
- KeePass via `keepassxc-cli` (`SSHJUMBERKEEPASSDATABASE`, `SSHJUMBERKEEPASSPASSWORD`)

### [1.5.0] - 2023-03-27
- Multi-hop password fields; selectable on-terminal display
- Removed auto copy-all-passwords-to-clipboard

### [1.4.0] - 2022-12-29
- Copy password without connecting

### [1.3.0] - 2022-11-16
- Copy password from passwords file into clipboard on connect

### [1.2.0] - 2022-07-18
- Local commands before SSH; config field renames; cleanup

### [1.1.0] - 2022-02-14
- Per-hop port (`&`) and identity key (`!`) in hop string

### [1.0.3] - 2021-11-06
- Clipboard password copy; `description` field

### [1.0.2] - 2020-05-12
- Tab completion for server names

### [1.0.1] - 2020-03-13
- Quiet mode for remote-command-only use

### [1.0.0] - 2019-09-28
- Initial configuration-driven multi-hop SSH jumper
- Optional terminal allocation and X11 forwarding

---

[Unreleased]: https://github.com/purushothamanpoovai/sshjumper/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/purushothamanpoovai/sshjumper/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/purushothamanpoovai/sshjumper/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/purushothamanpoovai/sshjumper/compare/v1.8.0...v2.0.0
[1.x]: https://github.com/purushothamanpoovai/sshjumper/releases

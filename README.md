# SSHJumper

Multi-hop SSH jumper that connects through a chain of hosts using **OpenSSH ProxyJump**. All identity keys stay on your local machine — no nested `ssh jump1 ssh jump2` commands.

Re-engineered from the original Bash implementation into a lightweight Python 3 CLI.

## Architecture

```text
Old:  local -> ssh jump1 -> ssh jump2 -> ssh final
New:  local -> OpenSSH ProxyJump chain -> final
```

Python only loads YAML, validates it, writes a minimal temporary `ssh_config`
(routing: Host, ProxyJump, keys), and runs the system `ssh` binary via
`subprocess`. OpenSSH alone handles authentication, known_hosts, ProxyJump,
terminal allocation, forwarding, and the full connection lifecycle.

## Requirements

- Python 3.9+
- OpenSSH client (`ssh`)
- pip (for installing vendor dependencies)

## Setup (one-click)

Supported: **Ubuntu/Debian**, **Fedora/RHEL/Rocky/Alma**, openSUSE, Arch.

```bash
git clone git@github.com:purushothamanpoovai/sshjumper.git
cd sshjumper
./install.sh
source ~/.sshjumper.rc
```

Prompts: `y` = yes · `a` = yes to all · `c` = cancel (system packages only).

### Config

| What | Path |
|------|------|
| **Config** | `~/.ssh/sshjumper/sshjconfig.yml` |
| Keys | `~/.ssh/ssh_keys/` |

```bash
$EDITOR ~/.ssh/sshjumper/sshjconfig.yml
```

### Connect

```bash
: server_name          # short alias (recommended)
: --list
: --gui                # interactive TUI
:                      # show help
sshjumper server_name  # same without alias
```

### Manual / vendor-only

```bash
./install-vendor.sh
chmod +x sshjumper
# then: ./install.sh   (or source ~/.sshjumper.rc after install)
```
## Config Format

System sections use a leading `_` so they are never mistaken for server names
(SSH-style defaults: `_global` applies to all servers; a per-server value wins).

```yaml
_global:
  keep_alive: true
  terminal: true

_hosts:
  prod_bastion:
    host: bastion.example.com
    user: ubuntu
    key: bastion.pem          # relative keys resolve from SSHJUMPERSSHKEYS

prod_db:
  description: production database
  environment: prod
  project: db
  remotecommand: sudo su -

  hop1: prod_bastion          # reuse _hosts.prod_bastion
  hop2:
    host: 10.0.1.20
    user: dbadmin

staging_app:
  hop1: prod_bastion          # same jump host
  hop2:
    host: 10.0.2.15
    user: appuser
```

Override a hop field when needed:

```yaml
hop1:
  use: prod_bastion
  port: 2222
```

Hops are ordered numerically: `hop1` → `hop2` → `hop10` (not lexicographic).
Top-level `_global:` and `_hosts:` are not connectable servers.
Legacy aliases `global:` / `hosts:` are still accepted.

### Server metadata

| Field | Description |
|-------|-------------|
| `description` | Shown before connecting |
| `environment` | Optional grouping label (e.g. `prod`, `staging`, `demo`) for TUI |
| `project` | Optional grouping label (e.g. `app`, `db`, `api`) for TUI |
| `keep_alive` | `ServerAliveInterval` / `ServerAliveCountMax` (often set once in `_global`) |
| `terminal` | Allocate TTY (default: true) |
| `x11` | X11 forwarding |
| `quiet` | `LogLevel=QUIET` |
| `verbose` | `-vvv` |
| `localcommand` | Shell command run locally before SSH |
| `remotecommand` | Command run on the final host |
| `copy`, `otp_secret`, `password`, `sudo` | Extension placeholders (phase 4) |

### Hop fields

| Field | Required | Description |
|-------|----------|-------------|
| `host` | yes* | Target hostname or IP (*or supplied via `_hosts` / `use`) |
| `user` | no | SSH user (defaults to local username) |
| `port` | no | SSH port |
| `key` | no | Identity file (relative or absolute) |
| `use` | no | Name of a template under top-level `_hosts:` |

A hop may also be a plain string (`hop1: prod_bastion`) meaning `use: prod_bastion`.

## Usage

```bash
sshjumper server_name                  # connect
sshjumper --gui                        # interactive TUI server picker
sshjumper                              # show help
sshjumper --list                       # list configured servers
sshjumper -i server_name               # dry-run / info mode
sshjumper -c /path/to/config.yml name  # custom config file
sshjumper -q server_name               # quiet SSH
sshjumper -v server_name               # verbose SSH
sshjumper -X server_name               # X11 forwarding
sshjumper --no-tty server_name         # disable terminal allocation
sshjumper server_name -- remote cmd    # run remote command
```

Aliases: `-i` (info), `-q` (quiet), `-v` (verbose), `-X` (x11), `-c` (config), `--gui` (TUI).

With the shell alias: `: server_name`, `: --gui`, `: --list`, bare `:` shows help.

## Interactive TUI

Open with `--gui` (not with empty args):

1. **TUI picker** — type anywhere to filter (no input box focus needed), **Tab** to complete, **Up/Down** to move in the list in parallel, **Enter** to connect
2. **SSH session** — full terminal; use `exit` or **Ctrl+D** to disconnect
3. **Returns to picker** — choose another server without re-running the command

Press **q** in the picker to quit entirely.

## How ProxyJump Works

For a three-hop server, a temporary config like this is generated:

```sshconfig
Host sshj_prod_db_hop1
    HostName bastion.example.com
    User ubuntu
    IdentityFile /home/user/.ssh/ssh_keys/bastion.pem

Host sshj_prod_db_hop2
    HostName 10.0.1.20
    User dbadmin
    ProxyJump sshj_prod_db_hop1
```

Then:

```bash
ssh -F /tmp/sshjumper_XXXX.conf sshj_prod_db_hop2
```

## Project Layout

```text
install.sh             # one-click installer
install-vendor.sh      # pip install into vendor/
install/               # shell rc templates
sshjumper              # entry point
sshjumper_cli/         # Python package
  extensions/          # plugin framework + builtin extensions
    builtin/           # passwords, clipboard, keepass, otp, terminal_title
configs/               # example configuration
vendor/                # vendored Python deps
```

## Extensions

Optional features run as **extensions** (enable / disable without changing core code).

```bash
sshjumper ext list
sshjumper ext enable otp
sshjumper ext disable clipboard
sshjumper ext path          # shows ~/.ssh/sshjumper/extensions.yml
```

| Extension | Default | Purpose |
|-----------|---------|---------|
| `gui` | on | Interactive Textual TUI (`--gui`) |
| `passwords` | on | Show password hints from server config |
| `keepass` | off | Lookup KeePass entry matching server name |
| `clipboard` | off | Copy KeePass/config secrets to clipboard |
| `otp` | off | OTP from `otp_secret` (oathtool) |
| `terminal_title` | off | Set / restore terminal title around SSH |

KeePass + clipboard example (`~/.ssh/sshjumper/extensions.yml`):

```yaml
enabled:
  keepass: true
  clipboard: true
config:
  keepass:
    database: /winshare/Keepass/Keypass-Database.kdbx
```

Set the master password via env (recommended):

```bash
export SSHJUMPERKEEPASSPASSWORD='your-master-password'
```

On connect, KeePass looks up an entry named like the server (`live_portal_db_1`, …) and clipboard copies that password. Override entry name per server with `keepass_entry: Other Title` in sshjconfig.

State file: `~/.ssh/sshjumper/extensions.yml`. New builtins can be added under `sshjumper_cli/extensions/builtin/` and registered in `builtin/__init__.py`.

## Migration from Bash / Old YAML

The old compact format:

```yaml
server:
  hops: user@jump!/key user@target
```

is replaced by structured `hop1`, `hop2`, … sections. See `configs/sshjconfig.example.yml`.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `SSHJUMPERCONFIGFILE` | Config file path |
| `SSHJUMPERPASSWORDFILE` | Passwords file (extensions) |
| `SSHJUMPERSSHKEYS` | Directory for relative key paths |
| `SSHJUMPEREXTENSIONSFILE` | Extension ON/OFF state (default `~/.ssh/sshjumper/extensions.yml`) |
| `SSHJUMPERKEEPASSDATABASE` | KeePass `.kdbx` path (overrides extensions.yml) |
| `SSHJUMPERKEEPASSPASSWORD` | KeePass master password (preferred over storing in YAML) |

## License

See repository for license details.

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

```yaml
prod_db:
  description: production database
  environment: prod
  project: db
  keep_alive: true
  terminal: true
  remotecommand: sudo su -

  hop1:
    host: bastion.example.com
    user: ubuntu
    key: bastion.pem          # relative keys resolve from SSHJUMPERSSHKEYS

  hop2:
    host: 10.0.1.20
    user: dbadmin
```

Hops are ordered numerically: `hop1` → `hop2` → `hop10` (not lexicographic).

### Server metadata

| Field | Description |
|-------|-------------|
| `description` | Shown before connecting |
| `environment` | Optional grouping label (e.g. `prod`, `staging`, `demo`) for TUI |
| `project` | Optional grouping label (e.g. `app`, `db`, `api`) for TUI |
| `keep_alive` | `ServerAliveInterval` / `ServerAliveCountMax` |
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
| `host` | yes | Target hostname or IP |
| `user` | no | SSH user (defaults to local username) |
| `port` | no | SSH port |
| `key` | no | Identity file (relative or absolute) |

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
install.sh             # one-click installer (platform check + deps + bashrc)
install-vendor.sh      # pip install into vendor/
install/
  sshjumper.rc         # template; live file is ~/.sshjumper.rc
  ssh-jumper-completion.rc
sshjumper              # entry point (sets up vendor path)
sshjumper_cli/         # Python package
vendor/                # pip-installed dependencies (PyYAML, Textual)
configs/               # example configuration
```

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

## License

See repository for license details.

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
  keep_alive: 30
  terminal: true
  ssh_options:                  # any OpenSSH option, on every connection
    WarnWeakCrypto: no-pq-kex

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
| `keep_alive` | seconds, e.g. `30` (`0` = off) → `ServerAliveInterval` + `ServerAliveCountMax 4` on every hop (often set once in `_global`) |
| `terminal` | Allocate TTY (default: true) |
| `x11` | X11 forwarding |
| `quiet` | `LogLevel=QUIET` |
| `verbose` | `-vvv` |
| `localcommand` | Shell command run locally before SSH |
| `remotecommand` | Command run on the final host |
| `ssh_options` | Any extra OpenSSH options as `Option: value` (see below) |
| `port_forward` | Local port forward(s) to the final host, applied only with `--port-forward` (see [Port forwarding](#port-forwarding)) |
| `copy`, `password`, `sudo` | Extension placeholders (phase 4) |

### Hop fields

| Field | Required | Description |
|-------|----------|-------------|
| `host` | yes* | Target hostname or IP (*or supplied via `_hosts` / `use`) |
| `user` | no | SSH user (defaults to local username) |
| `port` | no | SSH port |
| `key` | no | Identity file (relative or absolute) |
| `use` | no | Name of a template under top-level `_hosts:` |
| `port_forward` | no | Local port forward(s) to **this** hop, applied only with `--port-forward` |
| `totp` | no | TOTP source for this hop's verification-code prompt (needs the `otp` extension, see [TOTP](#totp-auto-fill)) |

A hop may also be a plain string (`hop1: prod_bastion`) meaning `use: prod_bastion`.

## Usage

```bash
sshjumper server_name                  # connect
sshjumper -g                           # interactive TUI server picker (--gui)
sshjumper                              # show help
sshjumper --list                       # list configured servers
sshjumper -E                           # edit sshjconfig.yml in $EDITOR, default vim (exits if already open)
sshjumper -k server_name               # copy KeePass password to clipboard, no login (clears in 30s)
sshjumper -o server_name               # copy current TOTP code to clipboard, no login (clears when it expires)
sshjumper -i server_name               # connection card: hops, keys, tunnels, commands
sshjumper -ii server_name              # connection card + copy/paste SSH commands
sshjumper -c /path/to/config.yml name  # custom config file
sshjumper -q server_name               # quiet SSH
sshjumper -v server_name               # verbose SSH
sshjumper -X server_name               # X11 forwarding
sshjumper -T server_name               # disable terminal allocation (--no-tty)
sshjumper server_name uptime           # run a remote command
sshjumper server_name -U ./app.tar /tmp/   # upload a file or folder (compressed scp -r through the jump chain)
sshjumper server_name -D /var/log/app ./   # download a file or folder
sshjumper server_name -P ls -P         # 1st -P is sshjumper's, 2nd -P goes to ls
sshjumper server_name -- -cmd --flag   # after --, everything goes to the remote host
sshjumper -P server_name               # connect + enable configured port_forward tunnels
```

Short options: `-c` config, `-i` / `-ii` info, `-E` edit-config, `-k` copy-pass, `-o` copy-otp, `-U` upload, `-D` download, `-l` list, `-g` gui, `-q` quiet, `-v` verbose, `-X` x11, `-P` port-forward, `-T` no-tty.

sshjumper options go before the server name or directly after it. The first other word after the server starts the remote command and everything from there is passed through unchanged. A remote command that itself starts with `-` must come after `--`. An unknown option is an error, never a remote command.

With the shell alias: `: server_name`, `: --gui`, `: --list`, bare `:` shows help.

## Connection preview (`-i` / `-ii`)

`-i` prints one compact view with everything about the connection: tags, description,
each hop with its role and key, tunnels, and the remote command. `-ii` adds the
copy/paste commands (nested SSH chain and ProxyJump) below it.

```text
live_portal_db_1  portal · prod · keep-alive
live aws portal db server 1

●
├── hop1  purushothaman@10.30.1.12
│   └ key     ~/.ssh/ssh_keys/aws_efs.pem
└── hop2  purushothaman@10.30.1.60
    └ tunnel  localhost:33061 ⇄ :3306
```

`●` is your machine. In the terminal, jump-host arrows are yellow and the target arrow is magenta.

## Port forwarding

Reach a port on a remote server (for example a database) from `localhost`, directly
or through any number of jump hosts. This is a local forward (`ssh -L`).

Forwards are **opt-in per run**: configured `port_forward` entries are used only
when you pass `--port-forward` (`-P`). Without the flag the connection is plain SSH.

```yaml
live_switch_db_archival_master:
  keep_alive: 30
  port_forward: 3000:3306        # server level: localhost:3000 -> final host:3306
  hop1: aws_efs_jump
  hop2:
    host: 10.30.1.70
    user: purushothaman
    port_forward: 3006:3306      # hop level: localhost:3006 -> this hop:3306
```

```bash
sshjumper -P live_switch_db_archival_master
# in another terminal, while the session is open, point your client at 127.0.0.1:3000
```

The tunnel lives as long as the SSH session is open.

**Where the forward goes**

| Placement | Target |
|-----------|--------|
| Top level of the server | The final hop |
| Inside `hopN:` (or a `_hosts` template) | That hop, including an intermediate jump host |

**Value forms** (a single value or a YAML list):

| Value | Meaning |
|-------|---------|
| `3306` | `localhost:3306` -> target hop `3306` |
| `3000:3306` | `localhost:3000` -> target hop `3306` |
| `3000:db.internal:3306` | `localhost:3000` -> `db.internal:3306`, resolved from the target hop |

```yaml
port_forward:
  - 3000:3306
  - 8080:app.internal:80
```

Notes:

- Write it with a space after the key: `port_forward: 3000:3306`. The form `port_forward:3000:3306` is not valid YAML.
- Local ports must be unique across the server's `port_forward` entries.
- The ProxyJump connection needs no ports opened on intermediate hosts. Traffic goes through the SSH chain.
- A forward to an *intermediate* hop is sent from the final host to that hop's `host` address, so the final host must be able to reach it. The nested copy/paste chain from `-i` relays the same local port through each hop instead (`ssh -L 3000:localhost:3000 jump 'ssh -L 3000:localhost:3306 db'`).
- Tunnels bind to `127.0.0.1` only (OpenSSH default).
- Jump hosts do **not** need their own `port_forward` to reach a port on the final host. They only relay the encrypted SSH connection. Use a hop-level `port_forward` only for a service running on that hop itself.
- If the connection fails (for example `connect to host ... port 22: Connection refused`), the tunnel was never created. Fix plain SSH first (VPN, `nc -vz <jump> 22`, security groups): if `sshjumper server` works, `sshjumper -P server` will too.
- `sshjumper -i server` shows each configured tunnel on the hop it ends at. Add `-P` when connecting to open them.
- `sshjumper -ii -P server` puts the `-L` flags in the copy/paste commands. Without `-P`, `-ii` warns that the tunnels are left out.

## TOTP auto-fill

Hops whose jump server asks for a `Verification code:` can have it typed for you. Set `totp:` on the hop (or its `_hosts` template) and enable the extension once with `sshjumper ext enable otp`.

```yaml
_hosts:
  jump_server_gw:
    host: 10.30.1.12
    user: purushothaman
    key: aws_efs.pem
    totp: keepass:jump_server_gw   # TOTP stored on that KeePass entry (recommended)
    # totp: env:GW_TOTP_SECRET     # base32 secret or otpauth:// URI in an env var
    # totp: file:~/.ssh/sshjumper/totp/gw.key   # must be chmod 600
    # totp: JBSWY3DPEHPK3PXP       # inline base32 (keep the config chmod 600)
```

How it works:

- ssh runs with `SSH_ASKPASS_REQUIRE=force` (OpenSSH 8.4+) and a small helper, so every prompt goes through sshjumper, including prompts from ProxyJump hops.
- A `(user@host) Verification code:` prompt for a hop with `totp` gets a code generated at that moment, so slow earlier hops never leave a later hop with an expired code. Codes with under 3s left are skipped, and a seed shared by two hops is never reused within the same 30s window.
- Every other prompt (passwords, host-key `yes/no`, key passphrases) and any second prompt for the same hop (a rejected code) is asked on your terminal as usual.
- Secrets stay inside the sshjumper process. The helper only receives the 6 digits, over a private unix socket (owner-only, per-connection token), and nothing secret is printed or logged.
- KeePass entries may store TOTP the KeePassXC way (`otp`), the KeePass 2 way (`TimeOtp-Secret-Base32`) or the legacy `TOTP Seed` way.

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

`-F` means `~/.ssh/config` is not read. Put any extra OpenSSH option under `ssh_options` instead.

### Extra OpenSSH options (`ssh_options`)

Any OpenSSH client option, written into the generated config as `Option value`:

```yaml
_global:
  ssh_options:                     # every server, every hop
    WarnWeakCrypto: no-pq-kex      # hide OpenSSH 10.1+ "not using a post-quantum key exchange" notice
    StrictHostKeyChecking: accept-new

_hosts:
  prod_bastion:
    host: bastion.example.com
    ssh_options:                   # this hop only (wherever the template is used)
      ConnectTimeout: 5

legacy_box:
  ssh_options:                     # this server: merged with _global, these win
    HostKeyAlgorithms: +ssh-rsa
    PubkeyAcceptedAlgorithms: +ssh-rsa
  hop1: prod_bastion
```

- Precedence: hop > server > `_global` (merged option by option).
- Values: text, numbers, or `true` / `false` (written as `yes` / `no`).
- `HostName`, `User`, `Port`, `IdentityFile`, `ProxyJump` are rejected here: they come from the hop fields. Use `keep_alive` rather than `ServerAliveInterval`.
- Names must be plain option names and values single-line, so an entry cannot inject other directives.
- Every option must be supported by the local OpenSSH, or ssh stops with `Bad configuration option` (e.g. `WarnWeakCrypto` needs OpenSSH 10.1+).

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
| `otp` | off | Auto-answer TOTP prompts for hops with `totp:` ([TOTP](#totp-auto-fill)) |
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

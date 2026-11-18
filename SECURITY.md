# Security

sshjumper is a **command builder and launcher** for the system OpenSSH client.
It never implements SSH itself and never sits between you and the server.

## How sshjumper handles your connection

| Area | What sshjumper does |
|------|---------------------|
| SSH protocol | None of its own. Connections, encryption and authentication are done entirely by the installed OpenSSH (`ssh`, `scp`) and `rsync`. No SSH or network library is used. |
| Network | sshjumper opens no network connections. Its only sockets are a private local unix socket (owner-only, per-run token, peer UID checked) that hands TOTP codes to ssh's `SSH_ASKPASS` helper. |
| Session traffic | Not read, recorded or changed. ssh is attached directly to your terminal. For `-u` / `-d` only rsync's local progress/summary lines and a one-word "is rsync installed" check are read. |
| Logging | No log files. Nothing is sent anywhere. |
| Generated ssh config | Temporary, mode `0600`, deleted after use; contains host names, users and key paths only (no secrets). |
| Passwords / TOTP | Kept in memory only. A password goes to the clipboard (cleared after 30s if unchanged); a TOTP code goes only to ssh's own prompt, generated at the moment it is asked for. Codes never reach the terminal or a file. |
| KeePass master password | Read from `~/.ssh/sshjumper/passwords.yml` (private file), else `SSHJUMPERKEEPASSPASSWORD`, else a prompt. The variable is removed from the environment so ssh, rsync, scp, `localcommand`, the editor and clipboard tools never inherit it. Passed to `keepassxc-cli` on stdin, never on the command line. |
| Config files | sshjumper refuses to start while `~/.ssh/sshjumper` is not `700` or `sshjconfig.yml`, `extensions.yml`, `passwords.yml` (or a `-c` config) are readable or writable by other users or owned by someone else; it prints the `chmod` to fix it. |
| Config injection | Hop `host` / `user` / `key` and `ssh_options` values are validated so a value cannot add extra directives to the generated ssh config. |
| File transfer | rsync only from version 3.4.0 (fixes CVE-2024-12084..12088), else scp. `--safe-links`, files written atomically, nothing deleted on the destination. |

## Security scans

Each release is checked with:

| Tool | Checks | Result (v3.4.0, 2026-11-18) |
|------|--------|-----------------------------|
| [Bandit](https://github.com/PyCQA/bandit) | Static analysis of `sshjumper_cli/` | No real issues. Reported items are reviewed: `localcommand` uses the shell by design (protected by the config ownership check); the YAML loader is a `SafeLoader` subclass; temp directories are created private (`0700`). |
| [pip-audit](https://github.com/pypa/pip-audit) | Known vulnerabilities (PyPI / OSV advisories) in all vendored libraries | No known vulnerabilities in the 22 bundled packages. |
| Manual review | Secret handling, process launching, file permissions, temp files, transfer semantics | Findings fixed (see `CHANGELOG.md`, Security sections). |

To repeat the scans:

```bash
pip install --target /tmp/sectools bandit pip-audit
PYTHONPATH=/tmp/sectools python3 -m bandit -r sshjumper_cli
ls vendor | grep dist-info | sed -E 's/-([0-9][^-]*)\.dist-info/==\1/' > /tmp/req.txt
PYTHONPATH=/tmp/sectools python3 -m pip_audit -r /tmp/req.txt --no-deps --disable-pip
```

A clean scan lowers risk; it does not prove the absence of bugs.

## Recommendations for users

- Keep `~/.ssh/sshjumper/` at `700` and its files at `600` (the installer does this).
- Keep the KeePass master password in `~/.ssh/sshjumper/passwords.yml` (or let sshjumper prompt), not in `~/.bashrc` or another shell startup file, which are often readable by other users.
- Prefer `totp: keepass:<entry>` over inline TOTP secrets in the config.
- Keep OpenSSH and rsync up to date. After a system Python upgrade, run `./install-vendor.sh`.

## Reporting a vulnerability

Please report security issues privately to the maintainer (GitHub: purushothamanpoovai) rather than in a public issue. Include the version (`git describe --tags`), steps to reproduce and the impact.

## Disclaimer

sshjumper is provided "as is", without warranty of any kind (see [LICENSE](LICENSE)). You use it at your own risk and remain responsible for your servers, credentials and for complying with your organisation's access and security policies.

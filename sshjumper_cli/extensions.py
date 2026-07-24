"""Extension points for advanced integrations (KeePass, OTP, clipboard, sudo)."""

from __future__ import annotations

from sshjumper_cli.config import ServerConfig


def run_extensions(server: ServerConfig) -> None:
    """Run optional pre-connect extensions. Non-blocking placeholders for phase 4."""
    if server.password:
        _display_passwords(server)
    if server.otp_secret:
        _otp_placeholder(server)
    if server.copy:
        _copy_placeholder(server)


def _display_passwords(server: ServerConfig) -> None:
    """Show configured password hints without copying to clipboard."""
    passwords = server.password
    if isinstance(passwords, dict):
        for name, value in passwords.items():
            print(f" {name}: \033[8m\033[48;5;15m{value}\033[0m")
    elif isinstance(passwords, str):
        print(f" password: \033[8m\033[48;5;15m{passwords}\033[0m")


def _otp_placeholder(server: ServerConfig) -> None:
    print("Note: OTP generation is not enabled in this build.")


def _copy_placeholder(server: ServerConfig) -> None:
    print(f"Note: clipboard copy for '{server.copy}' is not enabled in this build.")


def copy_pass_from_keepass(server_name: str) -> None:
    """KeePass integration placeholder."""
    return

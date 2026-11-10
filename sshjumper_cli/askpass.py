"""SSH_ASKPASS helper used by the otp extension.

OpenSSH runs this once per prompt (SSH_ASKPASS_REQUIRE=force) with the prompt
text as argv[1]. It asks the sshjumper process over a private unix socket;
if sshjumper has no answer (not a TOTP prompt, unknown host, retry after a
rejected code) the user is asked on the terminal exactly as ssh would.

Standalone on purpose: stdlib only, run with ``python3 -I``.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import termios


def _ask_server(prompt: str) -> str | None:
    path = os.environ.get("SSHJ_ASKPASS_SOCK")
    token = os.environ.get("SSHJ_ASKPASS_TOKEN")
    if not path or not token:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(120)  # server may wait for the next TOTP window
            sock.connect(path)
            sock.sendall(json.dumps({"token": token, "prompt": prompt}).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        answer = json.loads(data or b"{}").get("answer")
        return answer if isinstance(answer, str) else None
    except (OSError, ValueError):
        return None


def _ask_tty(prompt: str) -> str | None:
    """Prompt on the controlling terminal; echo only for yes/no style questions."""
    echo = "yes/no" in prompt.lower() or os.environ.get("SSH_ASKPASS_PROMPT") == "confirm"
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None
    try:
        os.write(fd, (prompt if prompt.endswith(" ") else prompt + " ").encode())
        old = termios.tcgetattr(fd)
        if not echo:
            new = termios.tcgetattr(fd)
            new[3] &= ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        data = b""
        try:
            while not data.endswith(b"\n"):
                chunk = os.read(fd, 1024)
                if not chunk:
                    break
                data += chunk
        except KeyboardInterrupt:
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSAFLUSH, old)
            if not echo:
                os.write(fd, b"\n")
        return data.decode(errors="replace").rstrip("\r\n") if data else None
    finally:
        os.close(fd)


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else ""
    answer = _ask_server(prompt)
    if answer is None:
        answer = _ask_tty(prompt)
    if answer is None:
        return 1  # ssh treats this as "cancelled"
    sys.stdout.write(answer + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

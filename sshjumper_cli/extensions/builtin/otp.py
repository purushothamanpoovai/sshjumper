"""Builtin extension: OTP via oathtool — stub ready for enable/disable."""

from __future__ import annotations

import shutil

from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext


class OtpExtension(BaseExtension):
    name = "otp"
    description = "Generate / refresh OTP from otp_secret (oathtool)"
    default_enabled = False

    def is_available(self) -> bool:
        return shutil.which("oathtool") is not None

    def pre_connect(self, ctx: ExtensionContext) -> None:
        if not ctx.server.otp_secret:
            return
        if not self.is_available():
            print("Note: otp extension needs oathtool on PATH.")
            return
        print("Note: otp extension is enabled but not fully implemented yet.")

"""
Backwards-compatible import location for wallet settings.

New code should use :mod:`wallet.conf`.
"""
from wallet.conf import DEFAULTS, get_wallet_setting, wallet_settings  # noqa: F401


class _SettingsView:
    """Dict-like, always-fresh view of the resolved settings (old ``WALLET_SETTINGS`` API)."""

    def __getitem__(self, name):
        return get_wallet_setting(name)

    def __contains__(self, name):
        return name in DEFAULTS

    def get(self, name, default=None):
        return get_wallet_setting(name) if name in DEFAULTS else default

    def keys(self):
        return DEFAULTS.keys()


WALLET_SETTINGS = _SettingsView()

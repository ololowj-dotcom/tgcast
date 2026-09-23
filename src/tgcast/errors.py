from __future__ import annotations


class GatewayError(Exception):
    pass


class NotFound(GatewayError):
    pass


class Forbidden(GatewayError):
    pass


class Transient(GatewayError):
    pass


class FloodWait(GatewayError):
    def __init__(self, seconds: int, message: str = ""):
        super().__init__(message or f"Telegram asks to wait {seconds}s")
        self.seconds = int(seconds)


class Restricted(GatewayError):
    pass


class Fatal(GatewayError):
    pass


class ConfigError(Exception):
    pass

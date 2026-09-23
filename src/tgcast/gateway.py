from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol

from .errors import Fatal, FloodWait, Forbidden, GatewayError, NotFound, Restricted, Transient
from .models import Resolved, Target


class Gateway(Protocol):
    def connect(self) -> None: ...
    def is_authorized(self) -> bool: ...
    def login(self, phone: str, ask_code: Callable[[], str], ask_password: Callable[[], str]) -> str: ...
    def resolve(self, target: Target) -> Resolved: ...

    def send(self, resolved: Resolved, text: str, attachment: Optional[Path], parse_mode: Optional[str],
             link_preview: bool) -> Optional[int]: ...
    def send_to_self(self, text: str) -> None: ...
    def close(self) -> None: ...


FLOOD_NAMES = {"FloodWaitError", "SlowModeWaitError", "FloodPremiumWaitError"}
RESTRICTED_NAMES = {"PeerFloodError"}
FATAL_NAMES = {
    "AuthKeyUnregisteredError", "AuthKeyInvalidError", "AuthKeyDuplicatedError", "SessionRevokedError",
    "SessionExpiredError", "UserDeactivatedError", "UserDeactivatedBanError", "PhoneNumberBannedError",
}
NOT_FOUND_NAMES = {
    "UsernameNotOccupiedError", "UsernameInvalidError", "PeerIdInvalidError", "InviteHashInvalidError",
    "InviteHashExpiredError",
}
FORBIDDEN_TEXT = {
    "ChatWriteForbiddenError": "you are not allowed to write in this chat",
    "UserBannedInChannelError": "your account is banned in this chat",
    "ChatAdminRequiredError": "only admins can post here",
    "ChatRestrictedError": "you are restricted in this chat",
    "ChannelPrivateError": "the chat is private or you were removed from it",
    "UserNotParticipantError": "you are not a member of this chat",
    "ChatGuestSendForbiddenError": "join the chat before writing to it",
    "ChannelBannedError": "the chat was banned by Telegram",
    "MessageTooLongError": "the message is too long for Telegram",
    "MessageEmptyError": "the message is empty",
    "MediaEmptyError": "the attachment could not be used",
    "ChatForbiddenError": "you cannot write in this chat",
    "TopicClosedError": "the topic is closed",
}
TRANSIENT_NAMES = {"ServerError", "TimedOutError", "RpcCallFailError", "InterdcCallErrorError"}


def map_error(exc: BaseException) -> GatewayError:
    if isinstance(exc, GatewayError):
        return exc
    name = type(exc).__name__
    if name in FLOOD_NAMES:
        return FloodWait(int(getattr(exc, "seconds", 60) or 60))
    if name in RESTRICTED_NAMES:
        return Restricted(
            "Telegram reports that your account is limited from messaging strangers (PeerFlood). "
            "Stop, wait a day or two and check @SpamBot before trying again."
        )
    if name in FATAL_NAMES:
        return Fatal(f"the Telegram session is no longer valid ({name}); run `tgcast setup` again")
    if name in NOT_FOUND_NAMES:
        return NotFound("no such chat or username")
    if name in FORBIDDEN_TEXT:
        return Forbidden(FORBIDDEN_TEXT[name])
    if name in TRANSIENT_NAMES or isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError)):
        return Transient(f"network problem: {exc or name}")
    return Forbidden(f"{name}: {exc}")


def has_rights(rights: Any, flag: str) -> bool:
    return bool(rights is not None and getattr(rights, flag, False))


def classify(entity: Any, peer_id: int, target: Target) -> Resolved:
    kind_name = type(entity).__name__
    title = getattr(entity, "title", None)
    if not title:
        title = " ".join(filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]))
    title = title or getattr(entity, "username", None) or str(peer_id)
    username = getattr(entity, "username", None)

    def result(kind: str, can_post: bool, reason: str = "", slowmode: bool = False) -> Resolved:
        return Resolved(target=target, id=peer_id, title=str(title), username=username, kind=kind,
                        can_post=can_post, reason=reason, slowmode=slowmode)

    if kind_name == "User":
        return result("user", False, "direct messages are not supported")
    if kind_name in ("ChatForbidden", "ChannelForbidden"):
        return result("unknown", False, "no access: you were removed or banned")
    is_admin = bool(getattr(entity, "creator", False) or getattr(entity, "admin_rights", None))
    if getattr(entity, "left", False):
        return result("group" if kind_name == "Chat" else "supergroup", False, "you are not a member of this chat")
    if kind_name == "Chat":
        if getattr(entity, "deactivated", False):
            return result("group", False, "the group was upgraded or deactivated")
        if has_rights(getattr(entity, "default_banned_rights", None), "send_messages") and not is_admin:
            return result("group", False, "members are not allowed to send messages")
        return result("group", True)
    if kind_name == "Channel":
        if getattr(entity, "broadcast", False):
            can = bool(getattr(entity, "creator", False) or has_rights(getattr(entity, "admin_rights", None), "post_messages"))
            return result("channel", can, "" if can else "you are not an admin with permission to post in this channel")
        if getattr(entity, "restricted", False):
            return result("supergroup", False, "the group is restricted by Telegram")
        slow = bool(getattr(entity, "slowmode_enabled", False))
        if has_rights(getattr(entity, "banned_rights", None), "send_messages"):
            return result("supergroup", False, "you are restricted in this group", slow)
        if has_rights(getattr(entity, "default_banned_rights", None), "send_messages") and not is_admin:
            return result("supergroup", False, "sending is disabled for members", slow)
        return result("supergroup", True, "", slow)
    return result("unknown", False, f"unsupported chat type {kind_name}")


class TelethonGateway:
    def __init__(self, api_id: int, api_hash: str, session: Path):
        from telethon import TelegramClient

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        name = str(session)
        if name.endswith(".session"):
            name = name[: -len(".session")]
        Path(name).parent.mkdir(parents=True, exist_ok=True)
        self.session_path = Path(name + ".session")
        self.client = TelegramClient(name, api_id, api_hash, flood_sleep_threshold=0)
        self.entities: Dict[int, Any] = {}
        self.dialogs_loaded = False

    def run(self, coro: Any) -> Any:
        try:
            return self.loop.run_until_complete(coro)
        except GatewayError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            raise map_error(exc) from exc

    def connect(self) -> None:
        self.run(self.client.connect())

    def is_authorized(self) -> bool:
        return bool(self.run(self.client.is_user_authorized()))

    def login(self, phone: str, ask_code: Callable[[], str], ask_password: Callable[[], str]) -> str:
        from telethon.errors import SessionPasswordNeededError

        async def flow() -> Any:
            await self.client.send_code_request(phone)
            try:
                await self.client.sign_in(phone, ask_code())
            except SessionPasswordNeededError:
                await self.client.sign_in(password=ask_password())
            return await self.client.get_me()

        me = self.run(flow())
        try:
            self.session_path.chmod(0o600)
        except OSError:
            pass
        return getattr(me, "username", None) and "@" + me.username or getattr(me, "first_name", "") or "account"

    def load_dialogs(self) -> None:
        if not self.dialogs_loaded:
            self.run(self.client.get_dialogs(limit=None))
            self.dialogs_loaded = True

    def resolve(self, target: Target) -> Resolved:
        from telethon import utils

        ref: Any = target.ref
        if ref.startswith("@"):
            ref = ref[1:]
        else:
            ref = int(ref)
            self.load_dialogs()
        entity = self.run(self.client.get_entity(ref))
        peer_id = utils.get_peer_id(entity)
        self.entities[peer_id] = entity
        return classify(entity, peer_id, target)

    def send(self, resolved: Resolved, text: str, attachment: Optional[Path], parse_mode: Optional[str],
             link_preview: bool) -> Optional[int]:
        entity = self.entities.get(resolved.id)
        if entity is None:
            raise NotFound("the chat was not resolved before sending")
        if attachment is not None:
            message = self.run(self.client.send_file(entity, str(attachment), caption=text, parse_mode=parse_mode))
        else:
            message = self.run(self.client.send_message(entity, text, parse_mode=parse_mode, link_preview=link_preview))
        return getattr(message, "id", None)

    def send_to_self(self, text: str) -> None:
        self.run(self.client.send_message("me", text))

    def close(self) -> None:
        try:
            self.run(self.client.disconnect())
        finally:
            self.loop.close()

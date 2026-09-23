import pytest
from telethon import errors

from tgcast.errors import FloodWait, Forbidden, NotFound, Restricted
from tgcast.gateway import TelethonGateway
from tgcast.models import Target


class Entity:
    def __init__(self, kind, **attrs):
        self.__class__ = type(kind, (Entity,), {})
        self.__dict__.update(attrs)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.entities = {}
        self.send_error = None
        self.sign_in_errors = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def is_user_authorized(self):
        return True

    async def send_code_request(self, phone):
        self.calls.append(("code", phone))

    async def sign_in(self, phone=None, code=None, password=None):
        self.calls.append(("sign_in", phone, code, password))
        if self.sign_in_errors:
            raise self.sign_in_errors.pop(0)

    async def get_me(self):
        return Entity("User", username="tester", first_name="Test")

    async def get_dialogs(self, limit=None):
        self.calls.append(("dialogs", limit))

    async def get_entity(self, ref):
        self.calls.append(("get_entity", ref))
        if ref not in self.entities:
            raise errors.UsernameNotOccupiedError(request=None)
        return self.entities[ref]

    async def send_message(self, entity, text, parse_mode=None, link_preview=None):
        self.calls.append(("send_message", entity, text, parse_mode, link_preview))
        if self.send_error:
            raise self.send_error
        return Entity("Message", id=501)

    async def send_file(self, entity, path, caption=None, parse_mode=None):
        self.calls.append(("send_file", entity, path, caption, parse_mode))
        return Entity("Message", id=502)


@pytest.fixture
def gw(tmp_path, monkeypatch):
    monkeypatch.setattr("telethon.utils.get_peer_id", lambda entity: entity.peer_id)
    gateway = TelethonGateway(12345, "abcdef", tmp_path / "sess" / "tgcast.session")
    gateway.client = FakeClient()
    yield gateway
    gateway.loop.close()


def group(peer_id=-100777, **attrs):
    base = {"title": "Devs", "megagroup": True, "username": "devs", "peer_id": peer_id}
    base.update(attrs)
    return Entity("Channel", **base)


def test_constructor_prepares_the_session_folder_and_strips_the_suffix(tmp_path):
    gateway = TelethonGateway(1, "h", tmp_path / "nested" / "tgcast.session")
    try:
        assert gateway.session_path == tmp_path / "nested" / "tgcast.session"
        assert (tmp_path / "nested").is_dir()
        assert gateway.client.flood_sleep_threshold == 0
    finally:
        gateway.loop.close()


def test_username_targets_are_resolved_and_classified(gw):
    gw.client.entities["devs"] = group()
    resolved = gw.resolve(Target("@devs"))
    assert (resolved.id, resolved.title, resolved.kind, resolved.can_post) == (-100777, "Devs", "supergroup", True)
    assert ("get_entity", "devs") in gw.client.calls and ("dialogs", None) not in gw.client.calls


def test_numeric_targets_load_dialogs_once(gw):
    gw.client.entities[-100777] = group()
    gw.client.entities[-100888] = group(-100888, title="Other")
    gw.resolve(Target("-100777"))
    gw.resolve(Target("-100888"))
    assert gw.client.calls.count(("dialogs", None)) == 1


def test_unknown_usernames_map_to_not_found(gw):
    with pytest.raises(NotFound):
        gw.resolve(Target("@nobody_here"))


def test_sending_text_uses_the_resolved_entity(gw):
    entity = group()
    gw.client.entities["devs"] = entity
    resolved = gw.resolve(Target("@devs"))
    assert gw.send(resolved, "hello", None, "markdown", False) == 501
    assert ("send_message", entity, "hello", "markdown", False) in gw.client.calls


def test_sending_with_an_attachment_uses_send_file(gw, tmp_path):
    gw.client.entities["devs"] = group()
    resolved = gw.resolve(Target("@devs"))
    picture = tmp_path / "pic.jpg"
    assert gw.send(resolved, "caption", picture, "html", True) == 502
    assert gw.client.calls[-1][0] == "send_file" and gw.client.calls[-1][3] == "caption"


def test_sending_to_an_unresolved_chat_is_refused(gw):
    from conftest import make_resolved
    with pytest.raises(NotFound):
        gw.send(make_resolved("@ghost_chat"), "x", None, None, False)


def test_real_telethon_errors_are_translated_while_sending(gw):
    gw.client.entities["devs"] = group()
    resolved = gw.resolve(Target("@devs"))
    gw.client.send_error = errors.FloodWaitError(request=None, capture=45)
    with pytest.raises(FloodWait) as flood:
        gw.send(resolved, "x", None, None, False)
    assert flood.value.seconds == 45
    gw.client.send_error = errors.PeerFloodError(request=None)
    with pytest.raises(Restricted):
        gw.send(resolved, "x", None, None, False)
    gw.client.send_error = errors.ChatWriteForbiddenError(request=None)
    with pytest.raises(Forbidden):
        gw.send(resolved, "x", None, None, False)


def test_send_to_self_targets_saved_messages(gw):
    gw.send_to_self("summary")
    assert gw.client.calls[-1][:3] == ("send_message", "me", "summary")


def test_login_with_a_code_only(gw):
    name = gw.login("+100", lambda: "12345", lambda: "unused")
    assert name == "@tester"
    assert ("sign_in", "+100", "12345", None) in gw.client.calls


def test_login_with_two_step_verification(gw):
    gw.client.sign_in_errors = [errors.SessionPasswordNeededError(request=None)]
    gw.login("+100", lambda: "12345", lambda: "s3cret")
    assert ("sign_in", None, None, "s3cret") in gw.client.calls


def test_connect_close_and_authorization(gw):
    gw.connect()
    assert gw.client.connected and gw.is_authorized() is True
    gw.close()
    assert not gw.client.connected
    gw.loop = __import__("asyncio").new_event_loop()


def test_close_works_when_disconnect_returns_nothing_like_the_real_client(tmp_path):
    gateway = TelethonGateway(1, "h", tmp_path / "s.session")
    calls = []

    class RealisticClient:
        def disconnect(self):
            calls.append("disconnect")

    gateway.client = RealisticClient()
    gateway.close()
    assert calls == ["disconnect"] and gateway.loop.is_closed()


def test_close_still_works_with_a_coroutine_disconnect(tmp_path):
    gateway = TelethonGateway(1, "h", tmp_path / "s.session")
    calls = []

    class AsyncClient:
        async def disconnect(self):
            calls.append("disconnect")

    gateway.client = AsyncClient()
    gateway.close()
    assert calls == ["disconnect"] and gateway.loop.is_closed()


def test_close_never_raises_even_if_disconnect_fails(tmp_path):
    gateway = TelethonGateway(1, "h", tmp_path / "s.session")

    class BrokenClient:
        def disconnect(self):
            raise RuntimeError("boom")

    gateway.client = BrokenClient()
    gateway.close()
    assert gateway.loop.is_closed()
    gateway.close()


@pytest.mark.parametrize("name,fragment", [
    ("ApiIdInvalidError", "api_id / api_hash pair is wrong"),
    ("PhoneNumberInvalidError", "international format"),
    ("PhoneCodeInvalidError", "login code is wrong"),
    ("PhoneCodeExpiredError", "expired"),
    ("PasswordHashInvalidError", "two-step"),
    ("PhoneNumberFloodError", "too many login attempts"),
])
def test_login_errors_are_explained_in_plain_language(name, fragment):
    from tgcast.gateway import map_error

    exc = getattr(errors, name)(request=None)
    mapped = map_error(exc)
    assert fragment in str(mapped) and "Error" not in str(mapped).split(":")[0]

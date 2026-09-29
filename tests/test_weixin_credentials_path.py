"""Per-instance isolation of the Weixin credentials (token) file.

A single Weixin channel keeps its legacy credentials path byte-for-byte; when
several instances run in one process each must get its own file so their tokens
do not overwrite one another.
"""

import json
import os

import config
from config import get_weixin_credentials_path


def _reset_conf(monkeypatch, **overrides):
    base = {"weixin_credentials_path": ""}
    base.update(overrides)
    monkeypatch.setattr(config, "conf", lambda: base)


def test_single_instance_keeps_legacy_path(monkeypatch):
    monkeypatch.delenv("COW_DATA_DIR", raising=False)
    _reset_conf(monkeypatch)
    assert get_weixin_credentials_path() == os.path.expanduser(
        "~/.weixin_cow_credentials.json"
    )


def test_instance_id_isolates_the_file(monkeypatch):
    monkeypatch.delenv("COW_DATA_DIR", raising=False)
    _reset_conf(monkeypatch)
    path = get_weixin_credentials_path("weixin-abc123")
    assert path == os.path.expanduser(
        "~/.weixin_cow_credentials.weixin-abc123.json"
    )
    # Two instances never resolve to the same file.
    assert path != get_weixin_credentials_path("weixin-def456")


def test_explicit_configured_path_is_suffixed_per_instance(monkeypatch, tmp_path):
    configured = str(tmp_path / "creds.json")
    _reset_conf(monkeypatch, weixin_credentials_path=configured)
    assert get_weixin_credentials_path() == configured
    assert get_weixin_credentials_path("weixin-xyz") == str(
        tmp_path / "creds.weixin-xyz.json"
    )


class TestAdoptingAnExistingLogin:
    """A login written before this instance had an id must survive.

    A channel that ran without an instance id left its login in the default
    file. Once the same channel comes back carrying an id, refusing that file
    means a working bot drops to a QR screen on restart. Adopting it is only
    safe while no other instance runs on it.
    """

    @staticmethod
    def _channel(tmp_path, instance_id, monkeypatch):
        import channel.weixin.weixin_channel as wc

        base = str(tmp_path / "creds.json")
        monkeypatch.setattr(
            wc, "get_weixin_credentials_path",
            lambda iid="": base if not iid else str(tmp_path / f"creds.{iid}.json"),
        )
        monkeypatch.setattr(wc, "_ACTIVE_LOGINS", {})
        cls = wc.WeixinChannel.__wrapped__
        ch = cls.__new__(cls)
        ch.instance_id = instance_id
        ch._credentials_path = str(tmp_path / f"creds.{instance_id}.json")
        ch._configured_logins = lambda: set()
        return ch, base

    def _write(self, path, token):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"token": token, "base_url": "https://example.test"}, f)

    def test_an_id_from_outside_may_adopt_an_unclaimed_login(self, tmp_path, monkeypatch):
        ch, base = self._channel(tmp_path, "d87bc864-d79e-4cb6", monkeypatch)
        self._write(base, "tok-legacy")

        assert ch._login_unclaimed("tok-legacy") is True

    def test_an_id_from_outside_adopts_only_on_a_cloud_deployment(self, monkeypatch):
        """Off the cloud, an id from outside is a separately provisioned bot:
        taking the local login would move the user's own WeChat onto it."""
        import channel.weixin.weixin_channel as wc

        cls = wc.WeixinChannel.__wrapped__
        monkeypatch.setattr(wc, "is_cloud_deployment", lambda: False)
        assert cls._may_adopt_default_login("d87bc864-d79e-4cb6") is False
        assert cls._may_adopt_default_login("weixin-0123456789") is True

        monkeypatch.setattr(wc, "is_cloud_deployment", lambda: True)
        assert cls._may_adopt_default_login("d87bc864-d79e-4cb6") is True

    def test_a_login_held_in_configured_credentials_is_not_adopted(self, tmp_path, monkeypatch):
        """The console's scan hands the token to the new instance's configured
        credentials, not to a credentials file of its own."""
        ch, base = self._channel(tmp_path, "second", monkeypatch)
        self._write(base, "tok-scanned")
        ch._configured_logins = lambda: {"tok-scanned"}

        assert ch._login_unclaimed("tok-scanned") is False

    def test_a_login_running_in_this_process_is_not_adopted(self, tmp_path, monkeypatch):
        import channel.weixin.weixin_channel as wc

        first, base = self._channel(tmp_path, "first", monkeypatch)
        second, _ = self._channel(tmp_path, "second", monkeypatch)
        self._write(base, "tok-live")
        first._hold_login("tok-live")

        assert second._login_unclaimed("tok-live") is False
        assert first._login_unclaimed("tok-live") is True

        first._hold_login("")
        assert "tok-live" not in wc._ACTIVE_LOGINS
        assert second._login_unclaimed("tok-live") is True

    def test_unreadable_configuration_counts_as_claimed(self, tmp_path, monkeypatch):
        ch, base = self._channel(tmp_path, "second", monkeypatch)
        self._write(base, "tok-legacy")

        def broken():
            raise RuntimeError("team.json unreadable")

        ch._configured_logins = broken
        assert ch._login_unclaimed("tok-legacy") is False

    def test_a_login_another_instance_runs_on_is_not_adopted(self, tmp_path, monkeypatch):
        ch, base = self._channel(tmp_path, "second", monkeypatch)
        self._write(base, "tok-legacy")
        # The first instance already copied that login into its own file.
        self._write(str(tmp_path / "creds.first.json"), "tok-legacy")

        assert ch._login_unclaimed("tok-legacy") is False

    def test_an_instance_does_not_count_as_claiming_against_itself(self, tmp_path, monkeypatch):
        ch, base = self._channel(tmp_path, "only", monkeypatch)
        self._write(base, "tok-legacy")
        self._write(ch._credentials_path, "tok-legacy")

        assert ch._login_unclaimed("tok-legacy") is True

    def test_a_different_login_next_door_leaves_this_one_free(self, tmp_path, monkeypatch):
        ch, base = self._channel(tmp_path, "second", monkeypatch)
        self._write(base, "tok-legacy")
        self._write(str(tmp_path / "creds.first.json"), "tok-other")

        assert ch._login_unclaimed("tok-legacy") is True

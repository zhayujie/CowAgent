"""Multi-instance channel resolution and persistence.

Two worlds must coexist: a legacy install driven by ``channel_type`` + flat
credentials, and a multi-instance install driven by an explicit
``channel_instances`` list in the roster file. These tests pin the legacy
behavior (so it never regresses) and cover the new persistence helpers.
"""

import os


from channel import channel_instances as ci


# ---------------------------------------------------------------------------
# instance id generation
# ---------------------------------------------------------------------------

def test_new_instance_id_has_type_prefix_and_is_unique():
    ids = set()
    for _ in range(50):
        new = ci.new_instance_id("feishu", ids)
        assert new.startswith("feishu-")
        assert new not in ids
        ids.add(new)


def test_new_instance_id_normalizes_type_and_handles_empty():
    assert ci.new_instance_id("wx").startswith("weixin-")
    assert ci.new_instance_id("").startswith("channel-")


def test_new_instance_id_avoids_taken():
    taken = {f"feishu-{i:010d}" for i in range(3)}
    assert ci.new_instance_id("feishu", taken) not in taken


# ---------------------------------------------------------------------------
# legacy compatibility: no channel_instances -> synthesized from channel_type
# ---------------------------------------------------------------------------

def test_legacy_channel_type_string(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": "feishu, dingtalk"}
    insts = ci.resolve_channel_instances(settings)
    ids = {i.instance_id for i in insts}
    assert ids == {"feishu", "dingtalk"}
    # legacy instances carry no per-instance credentials or binding
    for i in insts:
        assert i.legacy is True
        assert i.credentials == {}
        assert i.agent_id == ""


def test_legacy_channel_type_list(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": ["feishu"]}
    insts = ci.resolve_channel_instances(settings)
    assert [i.instance_id for i in insts] == ["feishu"]
    assert insts[0].legacy is True


def test_legacy_normalizes_wx(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": "wx"}
    insts = ci.resolve_channel_instances(settings)
    assert insts[0].channel_type == "weixin"


# ---------------------------------------------------------------------------
# explicit multi-instance resolution
# ---------------------------------------------------------------------------

def _write_instances(tmp_path, records):
    """Persist records to team.json and return settings with them overlaid.

    Mirrors how the launcher reads channels: team.resolve() lifts the roster
    file (where channel_instances lives) onto the flat settings before
    resolve_channel_instances() runs.
    """
    from agent import team

    base = {"agent_workspace": str(tmp_path)}
    team.write(base, {"channel_instances": records})
    return team.resolve(base)


def test_explicit_instances_win_over_legacy(tmp_path):
    settings = _write_instances(
        tmp_path,
        [
            {
                "instance_id": "feishu-a",
                "channel_type": "feishu",
                "agent_id": "default",
                "credentials": {"feishu_app_id": "A", "feishu_app_secret": "sa"},
            },
            {
                "instance_id": "feishu-b",
                "channel_type": "feishu",
                "agent_id": "ops",
                "credentials": {"feishu_app_id": "B", "feishu_app_secret": "sb"},
            },
        ],
    )
    settings["channel_type"] = "feishu"  # legacy field present but ignored
    insts = ci.resolve_channel_instances(settings)
    by_id = {i.instance_id: i for i in insts}
    assert set(by_id) == {"feishu-a", "feishu-b"}
    assert by_id["feishu-a"].agent_id == "default"
    assert by_id["feishu-b"].agent_id == "ops"
    assert by_id["feishu-a"].credentials["feishu_app_id"] == "A"
    assert all(i.legacy is False for i in insts)


def test_explicit_only_known_credential_keys_kept(tmp_path):
    settings = _write_instances(
        tmp_path,
        [
            {
                "instance_id": "feishu-a",
                "channel_type": "feishu",
                "credentials": {"feishu_app_id": "A", "junk": "x"},
            }
        ],
    )
    inst = ci.resolve_channel_instances(settings)[0]
    assert "feishu_app_id" in inst.credentials
    assert "junk" not in inst.credentials


# ---------------------------------------------------------------------------
# persistence helpers: upsert / update / remove
# ---------------------------------------------------------------------------

def test_upsert_creates_with_generated_id(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(
        settings,
        channel_type="feishu",
        agent_id="agent-x",
        credentials={"feishu_app_id": "A", "feishu_app_secret": "B", "junk": "no"},
    )
    assert inst.instance_id.startswith("feishu-")
    assert inst.agent_id == "agent-x"
    assert inst.credentials == {"feishu_app_id": "A", "feishu_app_secret": "B"}
    assert ci.read_raw_instances(settings)[0]["instance_id"] == inst.instance_id


def test_upsert_partial_update_keeps_binding(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(
        settings, channel_type="feishu", agent_id="agent-x",
        credentials={"feishu_app_id": "A", "feishu_app_secret": "B"},
    )
    # update credentials only, without re-sending agent_id
    updated = ci.upsert_instance(
        settings, channel_type="feishu", instance_id=inst.instance_id,
        credentials={"feishu_app_secret": "B2"},
    )
    assert updated.agent_id == "agent-x"  # binding preserved
    assert updated.credentials["feishu_app_secret"] == "B2"
    assert updated.credentials["feishu_app_id"] == "A"  # old value preserved
    # exactly one record: it was updated, not duplicated
    assert len(ci.read_raw_instances(settings)) == 1


def test_upsert_honors_provided_id(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(
        settings, channel_type="feishu", instance_id="from-remote-123",
        agent_id="a", credentials={"feishu_app_id": "A"},
    )
    assert inst.instance_id == "from-remote-123"


# ---------------------------------------------------------------------------
# instance name: a user-editable friendly label, seeded with a default and
# fully optional so legacy records without one keep working.
# ---------------------------------------------------------------------------

def test_new_instance_gets_default_name(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    first = ci.upsert_instance(settings, channel_type="weixin", credentials={})
    second = ci.upsert_instance(settings, channel_type="weixin", credentials={})
    # First of a type is unnumbered; the second is suffixed so they read apart.
    assert first.name == "微信"
    assert second.name == "微信 2"


def test_upsert_can_set_and_clear_name(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(settings, channel_type="feishu",
                              credentials={"feishu_app_id": "A"})
    renamed = ci.upsert_instance(settings, channel_type="feishu",
                                 instance_id=inst.instance_id, name="运营飞书")
    assert renamed.name == "运营飞书"
    # Renaming must not disturb credentials or duplicate the record.
    assert renamed.credentials["feishu_app_id"] == "A"
    assert len(ci.read_raw_instances(settings)) == 1
    # Empty name clears the label back to unset.
    cleared = ci.upsert_instance(settings, channel_type="feishu",
                                 instance_id=inst.instance_id, name="")
    assert cleared.name == ""


def test_upsert_partial_update_keeps_name(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(settings, channel_type="feishu", name="客服飞书",
                              credentials={"feishu_app_id": "A"})
    # A credentials-only update (name=None) must preserve the existing label.
    updated = ci.upsert_instance(settings, channel_type="feishu",
                                 instance_id=inst.instance_id,
                                 credentials={"feishu_app_secret": "S"})
    assert updated.name == "客服飞书"


def test_legacy_record_without_name_resolves(tmp_path):
    # A record written before the name field existed must still load, with an
    # empty name (the UI falls back to the id) and no error.
    settings = _write_instances(
        tmp_path,
        [{"instance_id": "feishu-old", "channel_type": "feishu",
          "credentials": {"feishu_app_id": "A"}}],
    )
    inst = ci.resolve_channel_instances(settings)[0]
    assert inst.name == ""
    assert inst.instance_id == "feishu-old"


def test_remove_instance(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(settings, channel_type="feishu",
                              credentials={"feishu_app_id": "A"})
    assert ci.remove_instance(settings, inst.instance_id) is True
    assert ci.read_raw_instances(settings) == []
    # removing a missing id is a no-op
    assert ci.remove_instance(settings, "nope") is False


# ---------------------------------------------------------------------------
# team members: a channel instance owns a roster (owner + teammates)
# ---------------------------------------------------------------------------

def test_explicit_instance_parses_members(tmp_path):
    settings = _write_instances(
        tmp_path,
        [
            {
                "instance_id": "feishu-team",
                "channel_type": "feishu",
                "agent_id": "leader",
                "members": ["ops", "research", "leader", "ops", ""],
                "credentials": {"feishu_app_id": "A"},
            }
        ],
    )
    inst = ci.resolve_channel_instances(settings)[0]
    # owner is never a member; duplicates and blanks are dropped; order kept
    assert inst.members == ["ops", "research"]


def test_upsert_sets_and_preserves_members(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(
        settings, channel_type="feishu", agent_id="leader",
        members=["ops", "leader", "research"],
        credentials={"feishu_app_id": "A"},
    )
    assert inst.members == ["ops", "research"]  # owner filtered out

    # a credentials-only update must not drop the team
    kept = ci.upsert_instance(
        settings, channel_type="feishu", instance_id=inst.instance_id,
        credentials={"feishu_app_secret": "S"},
    )
    assert kept.members == ["ops", "research"]

    # members=[] clears the team
    cleared = ci.upsert_instance(
        settings, channel_type="feishu", instance_id=inst.instance_id,
        members=[],
    )
    assert cleared.members == []
    assert "members" not in ci.read_raw_instances(settings)[0]


# ---------------------------------------------------------------------------
# bootstrap: carry a legacy flat feishu channel into channel_instances the
# first time the roster file is written (crossing into multi-Agent mode)
# ---------------------------------------------------------------------------

def test_bootstrap_synthesizes_feishu_from_flat_credentials(tmp_path):
    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "feishu",
        "feishu_app_id": "APP",
        "feishu_app_secret": "SECRET",
        "default_agent_id": "primary",
    }
    records = ci.bootstrap_legacy_instances(settings, {}, "primary")
    assert len(records) == 1
    rec = records[0]
    assert rec["instance_id"] == "feishu"
    assert rec["channel_type"] == "feishu"
    assert rec["agent_id"] == "primary"
    assert rec["credentials"] == {"feishu_app_id": "APP", "feishu_app_secret": "SECRET"}


def test_bootstrap_is_idempotent_when_feishu_record_exists(tmp_path):
    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "feishu",
        "feishu_app_id": "APP",
        "feishu_app_secret": "SECRET",
    }
    roster = {
        "channel_instances": [
            {"instance_id": "feishu-a", "channel_type": "feishu", "agent_id": "ops"}
        ]
    }
    records = ci.bootstrap_legacy_instances(settings, roster, "primary")
    # no duplicate feishu record was added
    assert [r["instance_id"] for r in records] == ["feishu-a"]


def test_bootstrap_skips_when_no_credentials(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": "feishu"}
    assert ci.bootstrap_legacy_instances(settings, {}, "primary") == []


def test_bootstrap_ignores_non_multi_instance_types(tmp_path):
    # wechatcom_app is a fixed-port webhook channel: it is not multi-instance
    # ready, so its flat config credentials must NOT be folded into an instance.
    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "wechatcom_app",
        "wechatcom_corp_id": "corp",
        "wechatcomapp_secret": "sec",
    }
    assert ci.bootstrap_legacy_instances(settings, {}, "primary") == []


def test_bootstrap_folds_multi_instance_types_beyond_feishu(tmp_path):
    # dingtalk is now multi-instance ready, so a legacy flat dingtalk config is
    # carried into a channel_instances record when crossing into multi-Agent
    # mode (otherwise multi-Agent startup, which skips the flat config entry for
    # multi-instance types, would drop it).
    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "dingtalk",
        "dingtalk_client_id": "id",
        "dingtalk_client_secret": "sec",
    }
    records = ci.bootstrap_legacy_instances(settings, {}, "primary")
    assert len(records) == 1
    assert records[0]["channel_type"] == "dingtalk"
    assert records[0]["agent_id"] == "primary"
    assert records[0]["credentials"]["dingtalk_client_id"] == "id"


def test_bootstrap_carries_weixin_token_file_to_instance_path(tmp_path, monkeypatch):
    # A scan-login Weixin user keeps their token in a credentials file, not in
    # config.json. Bootstrapping must copy that file to the per-instance path so
    # the user is not forced to re-scan after adding an Agent.
    import config

    legacy = tmp_path / "weixin_creds.json"
    legacy.write_text('{"token": "SCAN_TOKEN"}', encoding="utf-8")

    def fake_path(instance_id=""):
        if not instance_id:
            return str(legacy)
        root, ext = os.path.splitext(str(legacy))
        return f"{root}.{instance_id}{ext}"

    monkeypatch.setattr(config, "get_weixin_credentials_path", fake_path)

    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "weixin",
        "weixin_token": "",  # empty: token lives in the file, not config
    }
    records = ci.bootstrap_legacy_instances(settings, {}, "primary")
    assert any(r["channel_type"] == "weixin" for r in records)
    carried = tmp_path / "weixin_creds.weixin.json"
    assert carried.exists()
    assert "SCAN_TOKEN" in carried.read_text(encoding="utf-8")


def test_write_bootstraps_feishu_on_first_roster_write(tmp_path):
    """team.write folds a legacy flat feishu channel into channel_instances."""
    from agent import team

    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "feishu",
        "feishu_app_id": "APP",
        "feishu_app_secret": "SECRET",
        "default_agent_id": "primary",
    }
    team.write(settings, {"default_agent_id": "primary", "agents": []})
    resolved = team.resolve(settings)
    insts = ci.resolve_channel_instances(resolved)
    by_type = [i for i in insts if i.channel_type == "feishu"]
    assert len(by_type) == 1
    assert by_type[0].agent_id == "primary"
    assert by_type[0].credentials["feishu_app_id"] == "APP"

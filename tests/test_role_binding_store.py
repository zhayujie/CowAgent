import json
import threading

from channel.role_switch import RoleBindingStore


def test_empty_store_returns_no_binding(tmp_path):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    assert store.get_binding("weixin", "u1") is None
    assert store.get_bindings() == []


def test_set_and_get_binding(tmp_path):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    assert store.get_binding("weixin", "u1") == "coach"
    assert store.get_bindings() == [
        {"channel_type": "weixin", "conversation_id": "u1", "agent_id": "coach"}
    ]


def test_set_overwrites_same_key(tmp_path):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    store.set_binding("weixin", "u1", "translator")
    assert store.get_binding("weixin", "u1") == "translator"
    assert len(store.get_bindings()) == 1


def test_set_none_removes_binding(tmp_path):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    store.set_binding("weixin", "u1", None)
    assert store.get_binding("weixin", "u1") is None
    assert store.get_bindings() == []


def test_different_conversations_are_independent(tmp_path):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    store.set_binding("weixin", "u1", "coach")
    store.set_binding("weixin", "u2", "translator")
    assert store.get_binding("weixin", "u1") == "coach"
    assert store.get_binding("weixin", "u2") == "translator"


def test_remove_binding_returns_whether_removed(tmp_path):
    store = RoleBindingStore(str(tmp_path / "bindings.json"))
    assert store.remove_binding("weixin", "u1") is False
    store.set_binding("weixin", "u1", "coach")
    assert store.remove_binding("weixin", "u1") is True
    assert store.get_binding("weixin", "u1") is None


def test_persistence_across_reload(tmp_path):
    path = str(tmp_path / "bindings.json")
    RoleBindingStore(path).set_binding("weixin", "u1", "coach")
    store = RoleBindingStore(path)
    assert store.get_binding("weixin", "u1") == "coach"


def test_atomic_write_writes_utf8_json(tmp_path):
    path = str(tmp_path / "bindings.json")
    store = RoleBindingStore(path)
    store.set_binding("weixin", "u1", "coach")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == [
        {"channel_type": "weixin", "conversation_id": "u1", "agent_id": "coach"}
    ]
    assert not (tmp_path / "bindings.json.tmp").exists()


def test_corrupted_file_falls_back_to_empty(tmp_path):
    path = tmp_path / "bindings.json"
    path.write_text("{ not valid json", encoding="utf-8")
    store = RoleBindingStore(str(path))
    assert store.get_bindings() == []


def test_invalid_entries_are_skipped_on_load(tmp_path):
    path = tmp_path / "bindings.json"
    path.write_text(
        json.dumps(
            [
                {
                    "channel_type": "weixin",
                    "conversation_id": "u1",
                    "agent_id": "coach",
                },
                {"channel_type": "weixin", "conversation_id": "u2"},  # 缺 agent_id
                "not-a-dict",
                {"channel_type": "", "conversation_id": "u3", "agent_id": "coach"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = RoleBindingStore(str(path))
    assert store.get_bindings() == [
        {"channel_type": "weixin", "conversation_id": "u1", "agent_id": "coach"}
    ]
    assert store.get_binding("weixin", "u2") is None


def test_concurrent_writes_do_not_lose_bindings(tmp_path):
    path = str(tmp_path / "bindings.json")
    store = RoleBindingStore(path)
    results = []

    def writer(i):
        try:
            store.set_binding("weixin", f"u{i}", "coach")
            results.append(i)
        except Exception as e:  # pragma: no cover
            results.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 20
    store2 = RoleBindingStore(path)
    assert len(store2.get_bindings()) == 20

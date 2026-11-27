"""An exported variable must be able to come back in.

`load_config` imports environment variables into config, and `CONFIG_TO_ENV`
exports config keys back out for skill subprocesses. The import pass used to look
each variable up by its own lowercased name, so it only worked when the two
spellings happened to be related -- and several are not:

* `OPENAI_API_KEY` feeds `open_ai_api_key` (the conventional name everyone sets,
  versus this project's historical key).
* entries naming a key the config does not register at all were dropped with no
  log line, e.g. `DASHSCOPE_API_BASE`, `MINIMAX_API_BASE`, `QQ_APP_ID`.

Both failures are silent, which is what makes them worth a test rather than a
fix alone.
"""
import config as config_module


def _load_with(tmp_path, monkeypatch, env):
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    previous = config_module.config
    try:
        config_module.load_config()
        return dict(config_module.conf())
    finally:
        config_module.config = previous


def test_every_exported_key_is_registered():
    """`CONFIG_TO_ENV` naming an unregistered key is a variable that never lands."""
    missing = sorted(k for k in config_module.CONFIG_TO_ENV
                     if k not in config_module.available_setting)

    assert missing == []


def test_every_registered_key_is_lowercase():
    """Env names arrive lowercased, so a capitalised key can never be matched."""
    capitalised = sorted(k for k in config_module.available_setting if k != k.lower())

    assert capitalised == []


def test_the_export_table_has_no_duplicate_env_names():
    names = list(config_module.CONFIG_TO_ENV.values())
    duplicated = sorted({n for n in names if names.count(n) > 1})

    assert duplicated == []


def test_the_conventional_openai_name_reaches_the_config_key(tmp_path, monkeypatch):
    """`OPENAI_API_KEY` is what every deployment template and skill doc uses."""
    loaded = _load_with(tmp_path, monkeypatch, {"OPENAI_API_KEY": "sk-conventional"})

    assert loaded.get("open_ai_api_key") == "sk-conventional"


def test_the_historical_openai_name_still_works(tmp_path, monkeypatch):
    """Control: docker-compose sets OPEN_AI_API_KEY, which must keep working."""
    loaded = _load_with(tmp_path, monkeypatch, {"OPEN_AI_API_KEY": "sk-historical"})

    assert loaded.get("open_ai_api_key") == "sk-historical"


def test_every_endpoint_in_the_table_can_be_set_from_the_environment(tmp_path, monkeypatch):
    """One variable per entry, each asserted against the key the table names."""
    endpoints = {
        "DASHSCOPE_API_BASE": "dashscope_api_base",
        "MINIMAX_API_BASE": "minimax_api_base",
        "MOONSHOT_API_BASE": "moonshot_base_url",
        "ARK_API_BASE": "ark_base_url",
    }
    env = {name: f"https://{name.lower()}.example.test/v1" for name in endpoints}

    loaded = _load_with(tmp_path, monkeypatch, env)

    for env_name, key in endpoints.items():
        assert loaded.get(key) == env[env_name], f"{env_name} did not reach config['{key}']"


def test_the_qq_credentials_can_be_set_from_the_environment(tmp_path, monkeypatch):
    loaded = _load_with(tmp_path, monkeypatch,
                        {"QQ_APP_ID": "qq-app-102030405", "QQ_APP_SECRET": "s3cret"})

    assert loaded.get("qq_app_id") == "qq-app-102030405"
    assert loaded.get("qq_app_secret") == "s3cret"


def test_a_name_that_is_still_not_a_key_is_still_ignored(tmp_path, monkeypatch):
    """Control: the alias lookup must not become a wildcard."""
    loaded = _load_with(tmp_path, monkeypatch, {"NOT_A_COW_KEY_AT_ALL": "x"})

    assert "not_a_cow_key_at_all" not in loaded

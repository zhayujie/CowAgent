import io
import json
import os
import zipfile

import pytest

from channel.web.api import themes as themes_api
from channel.web.api.themes import ThemeImportError, collect_upload, import_theme, load_themes

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16


@pytest.fixture(autouse=True)
def cow_home(tmp_path, monkeypatch):
    monkeypatch.setattr(themes_api, "themes_dir", lambda: str(tmp_path / "themes"))
    return tmp_path


def _write_theme(root, folder, theme, files=()):
    path = root / "themes" / folder
    path.mkdir(parents=True)
    (path / "theme.json").write_text(json.dumps(theme))
    for name in files:
        (path / name).write_bytes(PNG)
    return path


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_conventional_images_are_picked_up_when_theme_json_omits_them(cow_home):
    _write_theme(cow_home, "moon", {"id": "moon", "name": "Moon"}, files=["wallpaper.jpg", "logo.png"])
    (theme,) = load_themes()
    assert theme["wallpaper"]["image"].startswith("/api/themes/asset?theme=moon&file=wallpaper.jpg")
    assert theme["wallpaper"]["glass"] is True
    assert theme["identity"]["logo"].startswith("/api/themes/asset?theme=moon&file=logo.png")


def test_declared_images_are_linked_and_missing_ones_dropped(cow_home):
    _write_theme(cow_home, "sun", {
        "id": "sun",
        "light": {"wallpaper": {"image": "light.png"}},
        "dark": {"wallpaper": {"image": "../../etc/passwd.png"}},
    }, files=["light.png"])
    (theme,) = load_themes()
    assert theme["light"]["wallpaper"]["image"].startswith("/api/themes/asset?theme=sun&file=light.png")
    assert "image" not in theme["dark"]["wallpaper"]
    # A declared wallpaper (even a broken one) turns off the folder fallback.
    assert "wallpaper" not in theme


def test_hidden_and_unreadable_folders_are_skipped(cow_home):
    _write_theme(cow_home, ".import-1", {"id": "half"})
    bad = cow_home / "themes" / "bad"
    bad.mkdir(parents=True)
    (bad / "theme.json").write_text("{not json")
    _write_theme(cow_home, "noid", {"name": "No id"})
    assert [t["id"] for t in load_themes()] == ["noid"]


def test_a_zip_with_a_top_level_folder_imports(cow_home):
    files, fallback = collect_upload([("pack.zip", _zip({
        "neon/theme.json": json.dumps({"name": "Neon"}),
        "neon/wallpaper.jpg": PNG,
        "neon/readme.txt": "skip me",
        "__MACOSX/neon/._theme.json": "junk",
    }))])
    assert sorted(files) == ["theme.json", "wallpaper.jpg"]
    assert import_theme(files, fallback, False, {"default"}) == {"status": "ok", "id": "neon", "name": "Neon"}
    assert (cow_home / "themes" / "neon" / "wallpaper.jpg").is_file()
    assert json.loads((cow_home / "themes" / "neon" / "theme.json").read_text())["id"] == "neon"


def test_reserved_ids_get_a_suffix_and_existing_ones_ask_first(cow_home):
    files = {"theme.json": json.dumps({"id": "ocean", "name": "Sea"}).encode()}
    assert import_theme(files, "", False, {"default", "ocean"})["id"] == "ocean-2"
    assert import_theme(files, "", False, {"default", "ocean"})["status"] == "exists"
    assert import_theme(files, "", True, {"default", "ocean"})["status"] == "ok"
    assert sorted(os.listdir(cow_home / "themes")) == ["ocean-2"]


@pytest.mark.parametrize("uploads, code", [
    ([("pack.zip", b"not a zip")], "bad_zip"),
    ([("pack.zip", _zip({"a/theme.json": "{}", "b/theme.json": "{}"}))], "no_theme"),
    ([("wallpaper.jpg", PNG)], "no_theme"),
    ([("theme.json", b"[1, 2]")], "bad_json"),
])
def test_bad_packages_are_refused(uploads, code):
    with pytest.raises(ThemeImportError) as err:
        files, fallback = collect_upload(uploads)
        import_theme(files, fallback, False, {"default"})
    assert err.value.code == code


def test_unsafe_paths_never_land_on_disk(cow_home):
    files, _ = collect_upload([
        ("theme.json", json.dumps({"id": "safe"}).encode()),
        ("../escape.png", PNG),
        ("/abs.png", PNG),
        ("sub/.hidden.png", PNG),
    ])
    assert sorted(files) == ["theme.json"]


def test_oversized_packages_are_refused(monkeypatch):
    monkeypatch.setattr(themes_api, "MAX_IMPORT_FILES", 2)
    with pytest.raises(ThemeImportError) as err:
        collect_upload([("theme.json", b"{}"), ("a.png", PNG), ("b.png", PNG)])
    assert err.value.code == "too_large"

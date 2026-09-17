"""Workspace-relative paths, and evaluate scripts written as a function body.

Both cost the model a turn: vision rejected a relative path that read had just
accepted, and browser.evaluate rejected a script with a top-level return that
the model then resent wrapped in an IIFE.
"""


from agent.tools.browser.browser_service import BrowserService
from agent.tools.vision.vision import Vision


def test_vision_resolves_relative_paths_against_the_workspace(tmp_path):
    (tmp_path / "tmp").mkdir()
    image = tmp_path / "tmp" / "shot.png"
    image.write_bytes(b"not really a png")

    tool = Vision({"cwd": str(tmp_path)})

    assert tool._resolve_path("tmp/shot.png") == str(image)


def test_vision_leaves_absolute_paths_alone(tmp_path):
    assert Vision({"cwd": str(tmp_path)})._resolve_path("/a/b.png") == "/a/b.png"


def test_vision_names_the_resolved_path_when_the_image_is_missing(tmp_path):
    tool = Vision({"cwd": str(tmp_path)})
    try:
        tool._build_image_content("tmp/missing.png")
    except FileNotFoundError as error:
        assert "tmp/missing.png" in str(error)
        assert str(tmp_path) in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_every_tool_can_receive_the_workspace():
    """The bridge assigns cwd unconditionally; BaseTool declares it."""
    from agent.tools.base_tool import BaseTool

    assert hasattr(BaseTool, "cwd")
    assert hasattr(Vision(), "cwd")


class _Page:
    """Playwright page that rejects a top-level return, like the real one."""

    def __init__(self):
        self.scripts = []

    def evaluate(self, script):
        self.scripts.append(script)
        if script.lstrip().startswith("const") and "return" in script:
            raise RuntimeError(
                "Page.evaluate: SyntaxError: Illegal return statement"
            )
        return {"bg": "rgb(10, 10, 10)"}


def _service_with(page):
    service = object.__new__(BrowserService)
    service._page = page
    return service


def test_evaluate_retries_a_function_body_wrapped_in_an_iife():
    page = _Page()

    result = _service_with(page)._do_evaluate(
        "const el = document.body; return {bg: getComputedStyle(el).backgroundColor}"
    )

    assert result == {"result": {"bg": "rgb(10, 10, 10)"}}
    assert len(page.scripts) == 2
    assert page.scripts[1].startswith("(() => {")
    assert page.scripts[1].endswith("})()")


def test_evaluate_does_not_wrap_a_script_that_already_works():
    page = _Page()

    _service_with(page)._do_evaluate("document.title")

    assert page.scripts == ["document.title"]


def test_unrelated_evaluate_errors_are_reported_as_is():
    class _Failing:
        def evaluate(self, script):
            raise RuntimeError("Page.evaluate: ReferenceError: foo is not defined")

    result = _service_with(_Failing())._do_evaluate("foo")

    assert "ReferenceError" in result["error"]

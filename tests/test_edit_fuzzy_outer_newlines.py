"""Fuzzy edits do not add a blank line for each outer newline of oldText.

The fuzzy matcher looks for oldText without its leading and trailing newlines,
so those newlines stay in the file around the match. Writing newText with its
own copies on top of them added one blank line per outer newline, while an
exact match of the same edit consumes them. Assertions are made on bytes, so
CRLF files are checked as written.
"""

import pytest

from agent.tools.edit.edit import Edit

TABLE = "| Option | Default |\n| ------ | ------- |\n| port   | 8080    |\n| host   | 0.0.0.0 |\n"
SCRIPT = "docker run \\\n\t--name app \\\n\t-p 8080:80 \\\n\tnginx\n"
MAKEFILE = "build:\n\tgo vet ./...\n\tgo build ./...\n\ntest:\n\tgo vet ./...\n\tgo test ./...\n"


@pytest.mark.parametrize("content,old,new,replace_all,expected", [
    # Collapsed table padding: a blank line would split the table in two.
    pytest.param(
        TABLE, "| port | 8080 |\n", "| port | 9090 |\n", False,
        TABLE.replace("| port   | 8080    |", "| port | 9090 |"),
        id="markdown-row",
    ),
    # Spaces sent for a tab: a blank line after the backslash ends the command.
    pytest.param(
        SCRIPT, "    --name app \\\n", "    --name web \\\n", False,
        SCRIPT.replace("app", "web"),
        id="shell-continuation",
    ),
    # The same edit with the file's own whitespace takes the exact path.
    pytest.param(
        SCRIPT, "\t--name app \\\n", "\t--name web \\\n", False,
        SCRIPT.replace("app", "web"),
        id="shell-continuation-exact",
    ),
    # Trailing spaces in the file, leading and trailing newline in the edit.
    pytest.param(
        "def f():\n    x = 1  \n    return x\n\n\ndef g():\n    return 2\n",
        "\n    x = 1\n    return x\n", "\n    x = 2\n    return x\n", False,
        "def f():\n    x = 2\n    return x\n\n\ndef g():\n    return 2\n",
        id="python-outer-newlines",
    ),
    # A newline newText adds beyond oldText's is still written, once.
    pytest.param(
        "func main() {\n\tx := 1\n\tfmt.Println(x)\n}\n",
        "    x := 1\n", "    x := 2\n\n", False,
        "func main() {\n\tx := 2\n\n\tfmt.Println(x)\n}\n",
        id="intended-blank-line",
    ),
    # A match that ends or starts partway through a line has no file newline
    # on that side, so newText's newline there is still written.
    pytest.param(
        "a = 1\n\tfoo()  # call\nb = 2\n", "    foo()\n", "    bar()\n", False,
        "a = 1\n\tbar()\n# call\nb = 2\n",
        id="match-ends-mid-line",
    ),
    pytest.param(
        "head  tail\nnext\n", "\ntail\n", "\nTAIL\n", False,
        "head  \nTAIL\nnext\n",
        id="match-starts-mid-line",
    ),
    # Every fuzzy match is replaced the same way, not only the first.
    pytest.param(
        MAKEFILE, "    go vet ./...\n", "    go vet -tags dev ./...\n", True,
        MAKEFILE.replace("go vet", "go vet -tags dev"),
        id="replace-all",
    ),
])
@pytest.mark.parametrize("ending", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_fuzzy_edit_adds_no_blank_lines(tmp_path, content, old, new, replace_all, expected, ending):
    path = tmp_path / "target.txt"
    path.write_bytes(content.replace("\n", ending).encode())
    result = Edit({"cwd": str(tmp_path)}).execute({
        "path": path.name, "oldText": old, "newText": new, "replaceAll": replace_all,
    })
    assert result.status == "success", result.result
    assert path.read_bytes() == expected.replace("\n", ending).encode()

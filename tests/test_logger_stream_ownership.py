"""Logger reconfiguration must not take ownership of caller-owned stdout."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("stream_kind", ["pipe", "file", "gbk", "stringio", "custom_stringio"])
def test_repeated_reset_preserves_stdout_and_emits_each_record_once(tmp_path, stream_kind):
    home = tmp_path / "home"
    home.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    script = r'''
import io,json,logging,sys
kind=sys.argv[1]
initial_stdout=sys.stdout
if kind == 'gbk':
    sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='gbk',errors='strict')
if kind in ('stringio','custom_stringio'):
    class CustomStringIO(io.StringIO):
        def isatty(self):
            return False
    sys.stdout = CustomStringIO() if kind == 'custom_stringio' else io.StringIO()
original=sys.stdout
from common.log import logger,_reset_logger
messages=[]
for index in range(4):
    if index:
        previous_files=[h for h in logger.handlers if isinstance(h,logging.FileHandler)]
        _reset_logger(logger)
        assert all(h.stream is None for h in previous_files), "reset leaked a file handler"
    assert not original.closed, 'reset closed stdout'
    assert sys.stdout is original, 'reset replaced caller stdout'
    assert len(logger.handlers)==2, 'reset duplicated or lost handlers'
    console=[h for h in logger.handlers if not isinstance(h,logging.FileHandler)]
    assert len(console)==1
    if kind == "gbk":
        assert original.encoding == "gbk", "reset mutated caller encoding"
    message='entry-'+str(index)+'-'+chr(0x1f389)
    messages.append(message)
    logger.info(message)
    sys.stdout.flush()
    del console
if hasattr(original,'getvalue'):
    text=original.getvalue()
    assert all(text.count(message)==1 for message in messages),text
print('stdout-still-usable')
sys.stdout.flush()
sys.stderr.write(json.dumps({'stdout_closed':original.closed,'messages':messages})+'\n')
'''
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
           "COW_DATA_DIR": str(data), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-B", "-c", script, stream_kind]
    output_path = tmp_path / "stdout.txt"
    if stream_kind == "file":
        with output_path.open("w", encoding="utf-8") as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", cwd=Path(__file__).resolve().parents[1],
                                    env=env, timeout=10)
        text = output_path.read_text(encoding="utf-8")
    else:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                cwd=Path(__file__).resolve().parents[1], env=env, timeout=10)
        text = result.stdout
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stderr)
    assert receipt["stdout_closed"] is False
    if stream_kind in ("file", "pipe", "gbk"):
        assert all(text.count(message)==1 for message in receipt["messages"])
        assert "stdout-still-usable" in text
    log = (data / "run.log").read_text(encoding="utf-8")
    assert all(log.count(message)==1 for message in receipt["messages"])

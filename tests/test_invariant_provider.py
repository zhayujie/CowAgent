import pytest
import os
import sys
import importlib.util
from pathlib import Path


@pytest.mark.parametrize("payload", [
    {"env_var": "OPENAI_API_KEY", "value": "sk-test123", "should_leak": False},
    {"env_var": "ANTHROPIC_API_KEY", "value": "", "should_leak": False},
    {"env_var": "COHERE_API_KEY", "value": "test_key_" + "x" * 1000, "should_leak": False},
])
def test_api_keys_not_exposed_in_module_attributes(payload, tmp_path, monkeypatch):
    """Invariant: API keys must not be exposed as module-level attributes or in error messages"""
    
    # Set environment variable with test API key
    monkeypatch.setenv(payload["env_var"], payload["value"])
    
    # Import the actual provider module
    provider_path = Path("agent/memory/embedding/provider.py")
    spec = importlib.util.spec_from_file_location("provider", provider_path)
    provider = importlib.util.module_from_spec(spec)
    
    # Capture any output during import
    import io
    from contextlib import redirect_stdout, redirect_stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        try:
            spec.loader.exec_module(provider)
        except Exception as e:
            error_msg = str(e)
            # API key must not appear in exception messages
            assert payload["value"] not in error_msg, f"API key leaked in exception: {error_msg}"
    
    # Check module attributes don't expose raw API keys
    for attr_name in dir(provider):
        attr_value = str(getattr(provider, attr_name, ""))
        if payload["value"] and len(payload["value"]) > 0:
            assert payload["value"] not in attr_value, f"API key leaked in module attribute: {attr_name}"
    
    # Check stdout/stderr don't contain API keys
    stdout_text = stdout_capture.getvalue()
    stderr_text = stderr_capture.getvalue()
    if payload["value"] and len(payload["value"]) > 0:
        assert payload["value"] not in stdout_text, "API key leaked to stdout"
        assert payload["value"] not in stderr_text, "API key leaked to stderr"
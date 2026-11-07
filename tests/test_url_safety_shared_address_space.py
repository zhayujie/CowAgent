import pytest

from agent.tools.utils import url_safety


@pytest.fixture(autouse=True)
def _enable_ssrf_guard(monkeypatch):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "1")


@pytest.mark.parametrize("addr", [
    "100.100.100.200",  # Alibaba Cloud metadata service
    "100.64.0.1",       # shared address space (RFC 6598)
    "127.0.0.1",
    "169.254.169.254",
    "10.0.0.1",
])
def test_non_public_addresses_are_blocked(addr):
    with pytest.raises(ValueError):
        url_safety.assert_public_ip(addr)


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(addr):
    url_safety.assert_public_ip(addr)

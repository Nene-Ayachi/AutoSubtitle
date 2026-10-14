"""Regression: proxy configuration must not fail before any model request."""
import importlib

import httpx
import pytest


@pytest.mark.parametrize('scheme', ['socks5', 'socks5h'])
def test_httpx_can_construct_socks_transport(scheme):
    # No connection is made: detects a missing SOCKS extra in the runtime.
    with httpx.Client(proxy=f'{scheme}://127.0.0.1:1080', trust_env=False):
        pass


@pytest.mark.parametrize('http_proxy', [False, True])
def test_actual_model_downloader_accepts_socks_environment(monkeypatch, http_proxy):
    for name in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv('all_proxy', 'socks5://127.0.0.1:1080')
    if http_proxy:
        monkeypatch.setenv('https_proxy', 'http://127.0.0.1:8080')
    # Exercise the real Hugging Face client's factory, including newer HTTPX variants.
    hub_http = importlib.import_module('huggingface_hub.utils._http')
    if not hasattr(hub_http, 'default_client_factory'):
        pytest.skip('This Hugging Face version uses the legacy requests backend')
    with hub_http.default_client_factory():
        pass

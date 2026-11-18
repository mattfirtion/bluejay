import json
import urllib.error

import pytest

import http_checks
from http_checks import Config, load_config, run_checks

JS_OK = (200, {"content-type": "application/javascript"}, b"x" * 2000, 50)
API_OK = (200, {}, b'{"results":[{"id":1}]}', 80)


@pytest.fixture
def cfg():
    return Config(
        index_js_url="https://search.example.com/index.js",
        api_url="https://search.example.com/api/q",
        api_body={"query": "example"},
        max_latency_ms=3000,
        index_js_min_bytes=1000,
        results_key="results",
    )


def fake(monkeypatch, index_js=JS_OK, api=API_OK):
    calls = []

    def _request(method, url, body, timeout):
        calls.append((method, url, body))
        result = index_js if url.endswith("index.js") else api
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(http_checks, "_request", _request)
    return calls


def test_all_pass(cfg, monkeypatch):
    fake(monkeypatch)
    run_checks(cfg)


def test_index_js_wrong_content_type_fails(cfg, monkeypatch):
    fake(monkeypatch, index_js=(200, {"content-type": "text/html"}, b"x" * 2000, 50))
    with pytest.raises(Exception, match="index.js"):
        run_checks(cfg)


def test_index_js_too_small_fails(cfg, monkeypatch):
    fake(monkeypatch, index_js=(200, {"content-type": "application/javascript"}, b"x" * 10, 50))
    with pytest.raises(Exception, match="index.js"):
        run_checks(cfg)


def test_index_js_slow_fails(cfg, monkeypatch):
    fake(monkeypatch, index_js=(200, {"content-type": "application/javascript"}, b"x" * 2000, 5000))
    with pytest.raises(Exception, match="index.js"):
        run_checks(cfg)


def test_api_empty_results_fails(cfg, monkeypatch):
    fake(monkeypatch, api=(200, {}, b'{"results":[]}', 80))
    with pytest.raises(Exception, match="/api/q"):
        run_checks(cfg)


def test_api_html_body_fails(cfg, monkeypatch):
    fake(monkeypatch, api=(200, {}, b"<html>error</html>", 80))
    with pytest.raises(Exception, match="/api/q"):
        run_checks(cfg)


def test_api_non_200_fails(cfg, monkeypatch):
    fake(monkeypatch, api=(503, {}, b"", 80))
    with pytest.raises(Exception, match="503") as exc:
        run_checks(cfg)
    assert "/api/q" in str(exc.value)


def test_api_posts_json_body(cfg, monkeypatch):
    calls = fake(monkeypatch)
    run_checks(cfg)
    api_calls = [c for c in calls if c[1].endswith("/api/q")]
    assert api_calls == [("POST", cfg.api_url, json.dumps(cfg.api_body).encode())]


def test_index_fails_api_passes_names_only_index_js(cfg, monkeypatch):
    fake(monkeypatch, index_js=(404, {}, b"", 50))
    with pytest.raises(Exception) as exc:
        run_checks(cfg)
    assert "index.js" in str(exc.value)
    assert "/api/q" not in str(exc.value)


def test_both_fail_names_both(cfg, monkeypatch):
    fake(monkeypatch, index_js=(404, {}, b"", 50), api=(503, {}, b"", 80))
    with pytest.raises(Exception) as exc:
        run_checks(cfg)
    assert "index.js" in str(exc.value)
    assert "/api/q" in str(exc.value)


def test_network_error_on_one_route_still_runs_other(cfg, monkeypatch):
    calls = fake(monkeypatch, index_js=OSError("boom"))
    with pytest.raises(Exception) as exc:
        run_checks(cfg)
    assert "index.js" in str(exc.value)
    assert any(c[1].endswith("/api/q") for c in calls)


def test_load_config_bad_body_raises():
    env = {"INDEX_JS_URL": "u", "API_URL": "a", "API_BODY": "{nope"}
    with pytest.raises(ValueError, match="API_BODY"):
        load_config(env)


def test_load_config_defaults():
    env = {"INDEX_JS_URL": "u", "API_URL": "a", "API_BODY": '{"q": 1}'}
    c = load_config(env)
    assert c.max_latency_ms == 3000
    assert c.index_js_min_bytes == 1000
    assert c.results_key == "results"
    assert c.api_body == {"q": 1}


def test_request_maps_http_error_to_status(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "unavailable", {}, None)

    monkeypatch.setattr(http_checks.urllib.request, "urlopen", boom)
    status, _headers, _body, _ms = http_checks._request("GET", "https://x.example.com/", None, 5)
    assert status == 503

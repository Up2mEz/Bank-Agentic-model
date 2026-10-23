"""Exercise HTTP parsing/auth/routes with in-memory sockets, never bind a port."""

import importlib
import importlib.util
import io
import json

import pytest
from test_review_service import payload, result, service_module

TOKEN = "synthetic-service-token-32-characters-only"


@pytest.mark.parametrize("token", [None, "wrong"])
def test_encoded_namespace_requires_auth_before_any_read_or_enqueue(tmp_path, token):
    with service_module().ReviewService(tmp_path / "jobs", runner=lambda p: result()) as s:
        handler = api_module().make_handler(s, TOKEN)
        assert (
            request(handler, "/%761/reviews", method="POST", body=payload(), token=token)[0] == 401
        )
        assert not s.process_next()
        job = s.submit(payload())
        for path in ["/%761/reviews/" + job["id"], "/%761/cases/CASE-service/review"]:
            status, value = request(handler, path, token=token)
            assert status == 401 and value == {"error": {"code": "UNAUTHORIZED"}}


def api_module():
    assert importlib.util.find_spec("merchant_sandbox.review_api"), "Review HTTP API missing"
    return importlib.import_module("merchant_sandbox.review_api")


def request(handler, path, *, method="GET", body=None, token=TOKEN, raw=None, headers=None):
    content = raw if raw is not None else json.dumps(body).encode() if body is not None else b""
    fields = {"Host": "localhost", "Content-Length": str(len(content))}
    if body is not None or raw is not None:
        fields["Content-Type"] = "application/json"
    if token is not None:
        fields["Authorization"] = "Bearer " + token
    fields.update(headers or {})
    wire = f"{method} {path} HTTP/1.0\r\n".encode()
    wire += "".join(f"{k}: {v}\r\n" for k, v in fields.items()).encode() + b"\r\n" + content

    class Socket:
        def __init__(self):
            self.sent = bytearray()

        def makefile(self, *args):
            return io.BytesIO(wire)

        def sendall(self, data):
            self.sent.extend(data)

        def settimeout(self, timeout):
            pass

    sock = Socket()
    handler(sock, ("127.0.0.1", 12345), object())
    head, data = bytes(sock.sent).split(b"\r\n\r\n", 1)
    return int(head.split()[1]), json.loads(data)


def test_http_auth_liveness_safe_readiness_submit_poll_latest(tmp_path):
    m = api_module()
    with service_module().ReviewService(tmp_path / "jobs", runner=lambda p: result()) as s:
        handler = m.make_handler(s, TOKEN)
        assert request(handler, "/healthz", token=None) == (200, {"status": "ok"})
        status, ready = request(handler, "/readyz", token=None)
        assert status == 200 and ready == {
            "ready": True,
            "modes": ["offline"],
            "typhoon_configured": False,
        }
        assert TOKEN not in json.dumps(ready)
        for path in ["/v1/reviews/x", "/v1/cases/CASE-service/review"]:
            assert request(handler, path, token=None)[0] == 401
        assert (
            request(handler, "/v1/reviews", method="POST", body=payload(), token="wrong")[0] == 401
        )
        status, job = request(handler, "/v1/reviews", method="POST", body=payload())
        assert status == 202 and job["status"] == "QUEUED"
        assert request(handler, "/v1/reviews", method="POST", body=payload())[1]["id"] == job["id"]
        s.process_next()
        status, done = request(handler, "/v1/reviews/" + job["id"])
        assert status == 200 and done["result"]["decision"] is None
        assert request(handler, "/v1/cases/CASE-service/review")[1] == done
        assert request(handler, "/v1/cases/missing/review")[0] == 404
        assert request(handler, "/v1/reviews/missing")[0] == 404


@pytest.mark.parametrize(
    "raw,headers,want",
    [
        (b"{", {}, 400),
        (b'{"mode":"offline","mode":"typhoon"}', {}, 400),
        (b'{"x":NaN}', {}, 400),
        (b"{}", {"Content-Type": "text/plain"}, 415),
        (b"{}", {"Content-Length": "-1"}, 400),
        (b"{}", {"Transfer-Encoding": "chunked"}, 400),
        (b"{}", {"Content-Length": "999999999"}, 413),
        (b"{}", {"Content-Length": "20"}, 400),
    ],
)
def test_bad_http_never_enqueues(tmp_path, raw, headers, want):
    m = api_module()
    with service_module().ReviewService(
        tmp_path / "jobs", runner=lambda p: pytest.fail("invalid")
    ) as s:
        handler = m.make_handler(s, TOKEN)
        assert request(handler, "/v1/reviews", method="POST", raw=raw, headers=headers)[0] == want
        assert not s.process_next()


def test_auth_loaded_only_explicitly_from_env_or_file(tmp_path, monkeypatch):
    m = api_module()
    monkeypatch.setenv("AGENT_SERVICE_TOKEN", TOKEN)
    assert m.load_token() == TOKEN
    file = tmp_path / "synthetic-token"
    file.write_text(TOKEN + "\n", encoding="utf-8")
    assert m.load_token(file) == TOKEN
    monkeypatch.setenv("AGENT_SERVICE_TOKEN", "short")
    with pytest.raises(ValueError):
        m.load_token()
    monkeypatch.delenv("AGENT_SERVICE_TOKEN")
    importlib.reload(m)  # No auth loading or listener/worker startup on import.


def test_wrong_methods_and_key_conflict_are_explicit(tmp_path):
    m = api_module()
    with service_module().ReviewService(tmp_path / "jobs", runner=lambda p: result()) as s:
        handler = m.make_handler(s, TOKEN)
        assert request(handler, "/v1/reviews", method="GET")[0] == 405
        assert request(handler, "/v1/cases/x/review", method="POST", body={})[0] == 405
        assert request(handler, "/v1/reviews", method="POST", body=payload())[0] == 202
        body = payload()
        body["mode"] = "typhoon"
        assert request(handler, "/v1/reviews", method="POST", body=body)[0] == 409


def test_http_factory_accepts_ephemeral_address_without_starting_worker(tmp_path, monkeypatch):
    m = api_module()
    observed = []

    def listener_double(address, handler):
        observed.append((address, handler))
        return "listener-double"

    monkeypatch.setattr(m, "ThreadingHTTPServer", listener_double)
    with service_module().ReviewService(tmp_path / "jobs", runner=lambda p: result()) as s:
        server = m.create_http_server(s, ("127.0.0.1", 0), token=TOKEN)
        assert server == "listener-double"
        assert observed[0][0] == ("127.0.0.1", 0)
        assert request(observed[0][1], "/healthz")[0] == 200
        assert s._worker is None


def test_cli_flags_pass_explicit_paths_and_default_host_port_without_real_listener(
    tmp_path, monkeypatch
):
    m = api_module()
    from merchant_sandbox.typhoon import Config

    calls = []
    monkeypatch.setattr(m, "load_token", lambda file: calls.append(("token", file)) or TOKEN)
    monkeypatch.setattr(Config, "load", lambda file: calls.append(("env", file)) or Config())

    class Server:
        def serve_forever(self):
            calls.append("serve")

        def server_close(self):
            calls.append("closed")

    def factory(service, address, **kwargs):
        assert kwargs["token"] == TOKEN
        calls.append(address)
        return Server()

    monkeypatch.setattr(m, "create_http_server", factory)
    m.main(
        [
            "--db",
            str(tmp_path / "jobs"),
            "--env-file",
            str(tmp_path / "synthetic.env"),
            "--token-file",
            str(tmp_path / "synthetic.token"),
        ]
    )
    assert ("127.0.0.1", 8781) in calls
    assert ("env", tmp_path / "synthetic.env") in calls
    assert ("token", tmp_path / "synthetic.token") in calls
    assert calls[-2:] == ["serve", "closed"]

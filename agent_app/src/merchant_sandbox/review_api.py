"""Authenticated evidence-review HTTP adapter. No startup or secret reads on import.

Run explicitly with ``python -m merchant_sandbox.review_api``. The factories are
reusable by an embedding application or an ephemeral in-process HTTP test.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .review_service import ReviewError, ReviewService


def load_token(token_file: str | Path | None = None) -> str:
    """Explicit file takes precedence over AGENT_SERVICE_TOKEN; never log either."""
    token = (
        Path(token_file).read_text(encoding="utf-8-sig").strip()
        if token_file is not None
        else os.environ.get("AGENT_SERVICE_TOKEN", "")
    )
    if (
        len(token) < 32
        or len(token) > 4096
        or not token.isascii()
        or any(c.isspace() for c in token)
    ):
        raise ValueError(
            "AGENT_SERVICE_TOKEN must contain 32..4096 non-whitespace ASCII characters"
        )
    return token


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON member")
        obj[key] = value
    return obj


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


def make_handler(service: ReviewService, token: str):
    """Return a BaseHTTPRequestHandler class; never bind a listener or run jobs."""
    if (
        not isinstance(token, str)
        or not 32 <= len(token) <= 4096
        or not token.isascii()
        or any(c.isspace() for c in token)
    ):
        raise ValueError("valid service token required")

    class Handler(BaseHTTPRequestHandler):
        server_version = "EvidenceReview/1"

        def setup(self):
            self.request.settimeout(15)
            super().setup()

        def log_message(self, fmt, *args):
            # URLs, request bodies and credentials never enter default access logs.
            pass

        def _send(self, status, value):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _authorized(self):
            values = self.headers.get_all("Authorization", [])
            supplied = values[0] if len(values) == 1 else ""
            return hmac.compare_digest(
                supplied.encode("utf-8"), ("Bearer " + token).encode("ascii")
            )

        def _body(self):
            if self.headers.get_all("Transfer-Encoding"):
                raise ReviewError("UNSUPPORTED_TRANSFER_ENCODING")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                raise ReviewError("INVALID_CONTENT_LENGTH")
            size = int(lengths[0])
            if size > service.max_payload_bytes:
                raise ReviewError("PAYLOAD_TOO_LARGE", 413)
            if self.headers.get_content_type() != "application/json":
                raise ReviewError("JSON_CONTENT_TYPE_REQUIRED", 415)
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ReviewError("INCOMPLETE_BODY")
            try:
                return json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                )
            except (UnicodeError, ValueError, RecursionError):
                raise ReviewError("INVALID_JSON") from None

        def _dispatch(self):
            try:
                path = urlsplit(self.path).path
                if path == "/healthz" and self.command == "GET":
                    self._send(200, {"status": "ok"})
                    return
                if path == "/readyz" and self.command == "GET":
                    capabilities = getattr(service.runner, "capabilities", None)
                    flags = (
                        capabilities()
                        if capabilities
                        else {
                            "ready": True,
                            "modes": ["offline"],
                            "typhoon_configured": False,
                        }
                    )
                    # Only these safe fields cross the liveness/capability boundary.
                    self._send(200, {k: flags[k] for k in ("ready", "modes", "typhoon_configured")})
                    return
                # Only the exact health routes above are public. Decoded routing
                # must never broaden the authentication boundary.
                if not self._authorized():
                    raise ReviewError("UNAUTHORIZED", 401)
                parts = [unquote(part) for part in path.strip("/").split("/")]
                if parts == ["v1", "reviews"]:
                    if self.command != "POST":
                        raise ReviewError("METHOD_NOT_ALLOWED", 405)
                    self._send(202, service.submit(self._body()))
                elif len(parts) == 3 and parts[:2] == ["v1", "reviews"]:
                    if self.command != "GET":
                        raise ReviewError("METHOD_NOT_ALLOWED", 405)
                    self._send(200, service.get(parts[2]))
                elif len(parts) == 4 and parts[:2] == ["v1", "cases"] and parts[3] == "review":
                    if self.command != "GET":
                        raise ReviewError("METHOD_NOT_ALLOWED", 405)
                    self._send(200, service.latest(parts[2]))
                else:
                    raise ReviewError("NOT_FOUND", 404)
            except ReviewError as exc:
                self._send(exc.status, {"error": {"code": exc.code}})
            except (TimeoutError, ConnectionError):
                self.close_connection = True
            except Exception:
                self._send(500, {"error": {"code": "INTERNAL_ERROR"}})

        do_GET = _dispatch
        do_POST = _dispatch
        do_PUT = _dispatch
        do_DELETE = _dispatch
        do_PATCH = _dispatch

    return Handler


def create_http_server(
    service: ReviewService,
    address: tuple[str, int] = ("127.0.0.1", 8781),
    *,
    token: str | None = None,
    token_file: str | Path | None = None,
) -> ThreadingHTTPServer:
    """Bind only when explicitly called. Port 0 supports ephemeral listener tests.

    Caller owns serve_forever/shutdown/server_close and the service/worker lifecycle.
    """
    handler = make_handler(service, token if token is not None else load_token(token_file))
    return ThreadingHTTPServer(address, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evidence assistant review service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args(argv)
    # Explicit CLI startup is the only eager configuration path.
    from .review_pipeline import ReviewPipeline
    from .typhoon import Config

    token = load_token(args.token_file)
    pipeline = ReviewPipeline(config=Config.load(args.env_file))
    with ReviewService(args.db, runner=pipeline) as service:
        server = create_http_server(service, (args.host, args.port), token=token)
        try:
            service.start_worker()
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()

"""Loopback-only, single-user experiment server. Not production authentication."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .bank import BankOnboardingClient
from .core import ROOT, SCENARIOS, BaselinePlanner, SandboxError, Store, default_input
from .lending import Documents, LendingController, app_input, customer_view
from .review import Reviews, staff_dossier
from .typhoon import Config, TyphoonPlanner


def database_lock(path):
    handle = path.with_suffix(".lock").open("a+b")
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except ImportError:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--bank-url", default="")
    parser.add_argument(
        "--bank-agent-key-file", type=Path, help="Server file for named Go role lending-agent"
    )
    parser.add_argument(
        "--bank-reviewer-key-file", type=Path, help="Server file for named Go role lending-reviewer"
    )
    parser.add_argument(
        "--bridge-token-file",
        type=Path,
        help="Server-only credential shared with Go; never included in Android",
    )
    parser.add_argument("--db", type=Path, default=ROOT / "outputs/merchant_sandbox/cases.sqlite3")
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    process_lock = database_lock(args.db)
    store = Store(args.db)
    store.recover()
    config = Config.load(args.env_file)
    token = (
        args.bridge_token_file.read_text().strip()
        if args.bridge_token_file
        else os.environ.get("LENDING_SERVICE_TOKEN", "")
    )
    if token and len(token) < 32:
        raise ValueError("LENDING_SERVICE_TOKEN must contain at least 32 characters")
    documents = Documents(store)
    bank = BankOnboardingClient(
        args.bank_url, args.bank_agent_key_file, args.bank_reviewer_key_file
    )
    controller = LendingController(store, documents, config, bank=bank)
    reviews = Reviews(store, documents, bank)
    review_nonce = secrets.token_urlsafe(32)
    # Keep run ownership visible before starting expensive network work.
    running: set[str] = set()
    run_lock = threading.Lock()

    def start_run(case_id, version, key=None):
        with run_lock:
            case, dispatch = reviews.accept_submit(case_id, version, idempotency_key=key)
            if not dispatch:
                return
            running.add(case_id)

        def work():
            try:
                controller.run(
                    case_id, TyphoonPlanner(config), version, _claimed_revision=case["revision"]
                )
            except (SandboxError, OSError):
                # Includes planner initialization errors before Controller.run owns cleanup.
                current = store.get(case_id)
                if current["active"] and current["revision"] == case["revision"]:
                    current.update(
                        active=False,
                        state="TECHNICAL_REVIEW",
                        feedback=["เริ่ม Agent ไม่สำเร็จ ตรวจการตั้งค่าและลองใหม่ด้วย key ใหม่"],
                    )
                    store.save(current)
            finally:
                with run_lock:
                    running.discard(case_id)

        threading.Thread(target=work, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Avoid logging user input or credentials.

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def check_local(self):
            hosts = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
            if self.headers.get("Host") not in hosts:
                raise SandboxError("Host ไม่ใช่ sandbox ในเครื่อง")
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in hosts}:
                raise SandboxError("ไม่รับคำสั่งจากเว็บอื่น")

        def projection(self, case):
            out = customer_view(case, documents)
            with run_lock:
                if case["id"] in running:
                    out["active"] = True
            return out

        def internal(self, path, data=None):
            if not token or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.send(401, {"error": "Invalid service authentication"})
                return
            if path == "/internal/agent/cases" or path.startswith("/internal/agent/cases/"):
                if data is not None:
                    self.send(405, {"error": "Agent routes are read only"})
                    return
                parts = path.strip("/").split("/")
                if len(parts) == 3:
                    self.send(
                        200,
                        {
                            "items": [
                                staff_dossier(c, documents)
                                for c in store.list()
                                if c.get("source") == "merchant_app"
                            ]
                        },
                    )
                elif len(parts) == 4:
                    try:
                        case = store.get(parts[3])
                        if case.get("source") != "merchant_app":
                            raise SandboxError("ไม่พบเคส")
                    except SandboxError:
                        self.send(404, {"error": "ไม่พบเคส"})
                        return
                    self.send(200, staff_dossier(case, documents))
                else:
                    self.send(404, {"error": "ไม่พบ route"})
                return
            try:
                owner = str(uuid.UUID(self.headers.get("X-Customer-ID", "")))
            except ValueError:
                self.send(401, {"error": "Missing authenticated customer"})
                return
            parts = path.strip("/").split("/")
            if parts[:3] != ["internal", "lending", "cases"]:
                self.send(404, {"error": "ไม่พบ route"})
                return
            # Read-only recovery for a gateway whose current readiness gate failed.
            # This path must never call create/start_run, even for an unseen key.
            if parts[3:] == ["replay"]:
                if data is None or set(data) != {"input", "idempotency_key"}:
                    raise SandboxError("ระบุ input และ idempotency_key เดิม")
                case = store.replay_create(
                    app_input(data["input"]), data["idempotency_key"], owner_id=owner
                )
                self.send(
                    200 if case else 404,
                    self.projection(case) if case else {"error": "ไม่พบ receipt"},
                )
                return
            if len(parts) == 3:
                if data is None:
                    with store.connect() as db:
                        rows = db.execute(
                            "SELECT payload FROM cases WHERE json_extract(payload,'$.owner_id')=? ORDER BY rowid DESC LIMIT 50",
                            (owner,),
                        ).fetchall()
                    self.send(200, {"items": [self.projection(json.loads(row[0])) for row in rows]})
                else:
                    case = store.create(
                        app_input(data["input"]), data["idempotency_key"], owner_id=owner
                    )
                    self.send(201, self.projection(case))
                return
            try:
                case = store.get(parts[3])
                if case.get("owner_id") != owner:
                    raise SandboxError("ไม่พบเคส")
            except SandboxError:
                self.send(404, {"error": "ไม่พบเคส"})
                return
            if data is None and len(parts) == 4:
                self.send(200, self.projection(case))
                return
            if data is not None and len(parts) >= 5:
                action = parts[4]
                if parts[4:] == ["submit", "replay"]:
                    if (
                        set(data) != {"version", "idempotency_key"}
                        or type(data["version"]) is not int
                        or data["idempotency_key"] is None
                    ):
                        raise SandboxError("ระบุ version และ idempotency_key เดิม")
                    replay = store.replay(
                        case, "submit", {"version": data["version"]}, data["idempotency_key"]
                    )
                    self.send(
                        200 if replay else 404,
                        self.projection(replay) if replay else {"error": "ไม่พบ receipt"},
                    )
                    return
                if action == "documents" and len(parts) == 5:
                    case = documents.change(
                        case,
                        data["version"],
                        data=data["document"],
                        idempotency_key=data.get("idempotency_key"),
                    )
                elif action == "documents" and len(parts) == 7 and parts[6] == "remove":
                    case = documents.change(
                        case,
                        data["version"],
                        remove=parts[5],
                        idempotency_key=data.get("idempotency_key"),
                    )
                elif action == "revise" and len(parts) == 5:
                    case = store.revise(
                        case["id"],
                        app_input(data["input"]),
                        data["version"],
                        idempotency_key=data.get("idempotency_key"),
                    )
                elif action == "submit" and len(parts) == 5:
                    start_run(case["id"], data["version"], data.get("idempotency_key"))
                    self.send(202, self.projection(store.get(case["id"])))
                    return
                else:
                    self.send(404, {"error": "ไม่พบ route"})
                    return
                self.send(200, self.projection(case))
                return
            self.send(404, {"error": "ไม่พบ route"})

        def do_GET(self):
            try:
                self.check_local()
                path = urlparse(self.path).path
                if path.startswith("/internal/"):
                    self.internal(path)
                elif path in {"/", "/lab"}:
                    self.send(
                        200,
                        (
                            Path(__file__).parent
                            / "static"
                            / ("index.html" if path == "/" else "lab.html")
                        ).read_bytes(),
                        "text/html; charset=utf-8",
                    )
                elif path == "/lending.js":
                    self.send(
                        200,
                        (Path(__file__).parent / "static/lending.js").read_bytes(),
                        "text/javascript; charset=utf-8",
                    )
                elif path == "/api/config":
                    self.send(
                        200,
                        {
                            "provider": Config.load(args.env_file).public(),
                            "scenarios": SCENARIOS,
                            "defaults": {k: default_input(k) for k in SCENARIOS},
                            "policy": controller.params["policy_version"],
                            "workspace": "OFFICER_REVIEW_SANDBOX",
                            "review_nonce": review_nonce,
                            "capabilities": {
                                "android_intake": "AUTHENTICATED_GO_GATEWAY"
                                if token
                                else "DISABLED",
                                "kyc": "GO_ONBOARDING" if bank.configured else "NOT_CONFIGURED",
                                "bank_review": bank.reviewer_configured,
                                "statement": "UPLOADED_DOCUMENT_OR_LAB_FIXTURE",
                                "document_ocr": "typhoon-ocr",
                                "human_decision_recording": "LOCAL_HUMAN_CAS",
                            },
                        },
                    )
                elif path == "/api/cases":
                    self.send(
                        200,
                        [
                            {
                                **{k: case[k] for k in ("id", "version", "state", "created_at")},
                                "applicant_name": case["input"]["applicant_name"],
                                "shop_name": case["input"]["shop_name"],
                                "requested_thb": case["input"]["requested_thb"],
                                "scenario_label": "Android / Merchant app"
                                if not case["is_mock"]
                                else SCENARIOS[case["input"]["scenario"]],
                                "recommendation": (case.get("packet") or {}).get("recommendation"),
                                "active": case["active"],
                                "is_mock": case["is_mock"],
                            }
                            for case in store.list()
                        ],
                    )
                elif path.startswith("/api/cases/") and len(path.split("/")) == 4:
                    case = store.get(path.split("/")[3])
                    self.send(200, {**case, "documents": documents.list(case)})
                elif (
                    path.startswith("/api/cases/")
                    and len(path.split("/")) == 5
                    and path.endswith("/onboarding")
                ):
                    self.send(200, reviews.read(path.split("/")[3]))
                elif path.startswith("/api/documents/") and len(path.split("/")) == 4:
                    raw, doc = documents.get(path.split("/")[3], raw=True)
                    self.send(200, raw, doc["mime_type"])
                else:
                    self.send(404, {"error": "ไม่พบ route"})
            except (SandboxError, ValueError, KeyError, TypeError) as exc:
                self.send(
                    getattr(exc, "status", 400),
                    {"error": str(exc), "code": getattr(exc, "code", "invalid_request")},
                )

        def do_POST(self):
            try:
                self.check_local()
                path = urlparse(self.path).path
                if not path.startswith("/internal/") and not hmac.compare_digest(
                    self.headers.get("X-Review-Nonce", ""), review_nonce
                ):
                    self.send(
                        403,
                        {"error": "โหลดหน้าเจ้าหน้าที่ใหม่ก่อนส่งคำสั่ง", "code": "review_nonce_required"},
                    )
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise SandboxError("ต้องใช้ application/json")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= (6 * 1024 * 1024 if path.startswith("/internal/") else 32_000):
                    raise SandboxError("request body ไม่ถูกต้องหรือใหญ่เกินขอบเขต")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise SandboxError("request ต้องเป็น JSON object")
                parts = path.split("/")
                if path.startswith("/internal/"):
                    self.internal(path, data)
                elif path == "/api/cases":
                    self.send(201, store.create(data["input"], data["idempotency_key"]))
                elif (
                    len(parts) == 6
                    and parts[1:3] == ["api", "cases"]
                    and parts[4] == "onboarding"
                    and parts[5] in {"kyc-decision", "kyb-decision"}
                ):
                    with run_lock:
                        self.send(
                            200,
                            {
                                **reviews.onboarding_decision(
                                    parts[3], parts[5].split("-")[0], data
                                ),
                                "documents": documents.list(store.get(parts[3])),
                            },
                        )
                elif len(parts) == 5 and parts[1:3] == ["api", "cases"]:
                    case_id, action = parts[3:]
                    if action == "revise":
                        self.send(
                            200,
                            store.revise(
                                case_id,
                                data["input"],
                                data["version"],
                                idempotency_key=data.get("idempotency_key"),
                            ),
                        )
                    elif action == "decision":
                        with run_lock:
                            case = reviews.decide(case_id, data)
                        self.send(200, {**case, "documents": documents.list(case)})
                    elif action == "run":
                        if store.get(case_id).get("source") == "merchant_app":
                            start_run(case_id, data["version"], data.get("idempotency_key"))
                            self.send(
                                202,
                                {
                                    **store.get(case_id),
                                    "active": case_id in running,
                                    "documents": documents.list(store.get(case_id)),
                                },
                            )
                            return
                        if data["mode"] not in {"baseline", "typhoon"}:
                            raise SandboxError("mode ไม่ถูกต้อง")
                        planner = (
                            BaselinePlanner()
                            if data["mode"] == "baseline"
                            else TyphoonPlanner(Config.load(args.env_file))
                        )
                        with run_lock:
                            if case_id in running:
                                raise SandboxError("เคสนี้กำลังทำงาน")
                            running.add(case_id)
                        try:
                            self.send(200, controller.run(case_id, planner, data["version"]))
                        finally:
                            with run_lock:
                                running.discard(case_id)
                    else:
                        self.send(404, {"error": "ไม่มี endpoint ตัดสิน/จ่ายเงินจริงใน sandbox นี้"})
                else:
                    self.send(404, {"error": "ไม่พบ route"})
            except (SandboxError, ValueError, KeyError, TypeError) as exc:
                message = str(exc) if isinstance(exc, SandboxError) else "รูปแบบ request ไม่ถูกต้อง"
                self.send(
                    getattr(exc, "status", 400),
                    {"error": message, "code": getattr(exc, "code", "invalid_request")},
                )

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(
        f"Merchant review: http://127.0.0.1:{args.port} (local development; demo lending policy)",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        process_lock.close()


if __name__ == "__main__":
    main()

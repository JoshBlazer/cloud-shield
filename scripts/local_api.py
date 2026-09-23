"""
Local full-stack API for CloudShield-Auditor.

Boots a fake AWS environment with Moto, seeds it with misconfigured resources,
runs one real audit (src.handler.lambda_handler), then serves the real API
Lambda (src.api.handler.api_handler) over HTTP so the dashboard can run against
the actual backend instead of its in-browser mock.

Run:
    python scripts/local_api.py                      # http://localhost:8787
    cd dashboard && VITE_USE_MOCK=false VITE_API_URL=http://localhost:8787 npm run dev

POST /audit/trigger starts another audit on a background thread and returns 202
at once, like the real endpoint's async Lambda invoke (a local audit takes ~15s).
Everything lives in memory and is gone when the server stops.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).parent.parent))

PORT = int(os.environ.get("PORT", "8787"))

# Allow the Vite dev/preview servers to call us.
os.environ.setdefault("DASHBOARD_URL", os.environ.get("DASHBOARD_ORIGIN", "http://localhost:5173"))

# local_run sets fake credentials and table names on import, and knows how to
# create the tables and seed misconfigured resources.
import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402
from scripts import local_run  # noqa: E402

_audit_lock = threading.Lock()


def _run_audit() -> None:
    from src.handler import lambda_handler
    try:
        lambda_handler({}, None)
    finally:
        _audit_lock.release()


class ApiRequestHandler(BaseHTTPRequestHandler):
    server_version = "CloudShieldLocal/1.0"

    def _dispatch(self) -> None:
        from src.api.handler import api_handler

        parts = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else None

        if self.command == "POST" and parts.path == "/audit/trigger":
            # No Lambda to invoke locally: run the audit on a thread, one at a
            # time (mirrors the auditor's reserved concurrency of 1).
            started = _audit_lock.acquire(blocking=False)
            if started:
                threading.Thread(target=_run_audit, daemon=True).start()
            origin = self.headers.get("Origin", "")
            msg = "Audit queued" if started else "An audit is already running"
            self._send(202, {"triggered": started, "message": msg}, origin)
            return

        event = {
            "httpMethod": self.command,
            "path": parts.path,
            "headers": dict(self.headers.items()),
            "queryStringParameters": dict(parse_qsl(parts.query)) or None,
            "body": body,
        }
        resp = api_handler(event, None)
        self.send_response(resp["statusCode"])
        for k, v in (resp.get("headers") or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write((resp.get("body") or "").encode())

    def _send(self, status: int, payload: object, origin: str) -> None:
        from src.api.handler import _cors
        self.send_response(status)
        for k, v in {**_cors(origin), "Content-Type": "application/json"}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    do_GET = do_POST = do_PATCH = do_OPTIONS = _dispatch  # noqa: N815

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")


def main() -> None:
    with mock_aws():
        session = boto3.Session(region_name=local_run.REGION)
        local_run.seed_tables(session)
        local_run.seed_violations(session)
        local_run.seed_sns(session)

        from src.handler import lambda_handler
        result = lambda_handler({}, None)
        print(f"\nSeeded: {len(result['violations'])} findings from {result['resources_audited']} resources.")
        print(f"CloudShield local API on http://localhost:{PORT}  (CORS origin: {os.environ['DASHBOARD_URL']})\n")

        ThreadingHTTPServer(("127.0.0.1", PORT), ApiRequestHandler).serve_forever()


if __name__ == "__main__":
    main()

"""Local HTTP API (stdlib) over the same core functions the CLI uses. Placeholder for a dashboard/chat.

GET /health · /query?q=..&project=..&kind=.. · /items/<id> · /stats?project=..&days=7 · /outbox?project=..
Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .indexes import Query
from .query import search
from .stats import summary
from .store import LocalStore
from .telemetry import Telemetry
from .tune import list_outbox


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object) -> None:
        data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:   # quiet
        pass

    def do_GET(self) -> None:
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/health":
                return self._send(200, {"ok": True, "version": __version__})
            if url.path == "/query":
                q = Query(text=qs.get("q", ""), project=qs.get("project"),
                          kinds=qs["kind"].split(",") if qs.get("kind") else None, limit=int(qs.get("limit", 10)))
                return self._send(200, search(LocalStore(), q))
            if url.path.startswith("/items/"):
                item = LocalStore().get(url.path.split("/", 2)[2])
                return self._send(200, item.__dict__) if item else self._send(404, {"error": "not found"})
            if url.path == "/stats":
                return self._send(200, summary(Telemetry(), qs.get("project"), int(qs.get("days", 7))))
            if url.path == "/outbox":
                return self._send(200, list_outbox(qs.get("project")))
            return self._send(404, {"error": "unknown path"})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})


def serve(port: int = 8765) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"agent-kb API on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    httpd.serve_forever()

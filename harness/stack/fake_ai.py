"""Stand-in AI for the harness: an OpenAI-compatible chat completions server.

The test stack points the app's DeepSeek calls here (OE_DEEPSEEK_URL), so AI
features run in CI with no key and nothing leaves the machine. Standard
library only, so it runs on the plain python image.

  POST /chat/completions, /v1/chat/completions   answer like DeepSeek would
  GET  /_harness/requests                        every request received, oldest first
  DELETE /_harness/requests                      forget them
  POST /_harness/replies   {"replies": [...]}    queue exact answers for the next calls
  GET  /health                                   liveness

Without a queued reply the answer is a fixed Bulgarian sentence, or the text
after a line "HARNESS_REPLY:" in the last user message.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_REPLY = "Тестов отговор от заместващия AI."
MAX_RECORDED = 500

_lock = threading.Lock()
_requests: deque[dict] = deque(maxlen=MAX_RECORDED)
_replies: deque[str] = deque()


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _answer(body: dict) -> str:
    with _lock:
        if _replies:
            return _replies.popleft()
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user":
            continue
        for line in _text(message.get("content")).splitlines():
            if line.startswith("HARNESS_REPLY:"):
                return line.removeprefix("HARNESS_REPLY:").strip()
        break
    return DEFAULT_REPLY


class Handler(BaseHTTPRequestHandler):
    server_version = "harness-fake-ai/1"

    def log_message(self, fmt: str, *args: object) -> None:  # one line per call, to stdout
        print(f"{self.command} {self.path} {fmt % args}", flush=True)

    def _json(self, status: int, payload: object) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        elif self.path == "/_harness/requests":
            with _lock:
                self._json(200, list(_requests))
        else:
            self._json(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        if self.path == "/_harness/requests":
            with _lock:
                _requests.clear()
                _replies.clear()
            self._json(200, {"cleared": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._body()
        if self.path == "/_harness/replies":
            with _lock:
                _replies.extend(str(r) for r in body.get("replies") or [])
            self._json(200, {"queued": len(_replies)})
            return
        if self.path not in ("/chat/completions", "/v1/chat/completions"):
            self._json(404, {"error": "not found"})
            return

        with _lock:
            _requests.append(
                {
                    "at": time.time(),
                    "path": self.path,
                    "authorization": bool(self.headers.get("Authorization")),
                    "body": body,
                }
            )
        reply = _answer(body)
        model = body.get("model") or "deepseek-chat"
        prompt_tokens = sum(len(_text(m.get("content")).split()) for m in body.get("messages") or [])
        completion_tokens = len(reply.split())
        ident = f"harness-{uuid.uuid4().hex[:12]}"

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for delta, finish in (({"role": "assistant", "content": reply}, None), ({}, "stop")):
                chunk = {
                    "id": ident,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return

        self._json(
            200,
            {
                "id": ident,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            },
        )


if __name__ == "__main__":
    print("Stand-in AI listening on :8000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()

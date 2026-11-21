"""Reference consumer 3: a mock API server.  Frozen as written (RELEASING.org).

    python3 mock_server.py path/to/stacks.jsonl

Binds 127.0.0.1 on an ephemeral port and prints `PORT <n>` on stdout.
GET /stacks serves the last line of the file, byte for byte (without its
newline), as application/json.  The file is read on every request, so it
behaves like `tail -1` on a live log.  404 when the file is missing or
holds no line, and for any other path.  Standard library only.
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def last_line(log_path: Path) -> bytes | None:
    try:
        content = log_path.read_bytes()
    except OSError:
        return None
    lines = [line for line in content.split(b"\n") if line]
    return lines[-1] if lines else None


def make_handler(log_path: Path) -> type[BaseHTTPRequestHandler]:
    class StacksHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            body = last_line(log_path) if self.path == "/stacks" else None
            if body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # quiet: stdout carries only the PORT line

    return StacksHandler


def main() -> None:
    log_path = Path(sys.argv[1])
    server = HTTPServer(("127.0.0.1", 0), make_handler(log_path))
    print(f"PORT {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

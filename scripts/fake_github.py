"""A tiny fake GitHub API for the end-to-end demo (no real GitHub account needed).

Serves one pull request (yaswanth0702/demo#42) containing a SQL-injection bug, and records any
review that DevPilot posts. Run:  python scripts/fake_github.py  (listens on :9000)
Then GET http://localhost:9000/_reviews to see what DevPilot posted.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PATH = "app/users.py"
BEFORE = "def get_user(conn, user_id):\n    return None\n"
AFTER = (
    "def get_user(conn, user_id):\n"
    "    cur = conn.cursor()\n"
    "    cur.execute(\"SELECT * FROM users WHERE id=\" + user_id)\n"
    "    return cur.fetchone()\n"
)
DIFF = f"""diff --git a/{PATH} b/{PATH}
--- a/{PATH}
+++ b/{PATH}
@@ -1,2 +1,4 @@
 def get_user(conn, user_id):
-    return None
+    cur = conn.cursor()
+    cur.execute("SELECT * FROM users WHERE id=" + user_id)
+    return cur.fetchone()
"""
HEAD_SHA = "3f2a9c1e0b7d4a5f8e6c2b1a0d9e8f7c6b5a4d3e"
REVIEWS: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        accept = self.headers.get("Accept", "")
        if p == "/_reviews":
            return self._send(200, REVIEWS)
        if p == "/repos/yaswanth0702/demo/pulls/42":
            if "diff" in accept:
                return self._send(200, DIFF, "text/plain")
            return self._send(200, {"number": 42, "head": {"sha": HEAD_SHA}})
        if p == "/repos/yaswanth0702/demo/pulls/42/files":
            return self._send(200, [{"filename": PATH}])
        if p == f"/repos/yaswanth0702/demo/contents/{PATH}":
            return self._send(200, AFTER, "text/plain")
        return self._send(404, {"message": "Not Found"})

    def _read_body(self) -> bytes:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            data = b""
            while True:
                size = int(self.rfile.readline().strip(), 16)
                if size == 0:
                    self.rfile.readline()
                    return data
                data += self.rfile.read(size)
                self.rfile.readline()
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_POST(self):
        body = json.loads(self._read_body() or b"{}")
        if self.path == "/repos/yaswanth0702/demo/pulls/42/reviews":
            REVIEWS.append(body)
            return self._send(200, {"id": len(REVIEWS)})
        return self._send(404, {"message": "Not Found"})

    def log_message(self, fmt, *args):
        print("fake-github:", fmt % args)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9000), Handler).serve_forever()

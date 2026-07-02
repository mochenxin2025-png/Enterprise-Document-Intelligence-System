"""HTTP Tool Server — 通过 HTTP API 暴露 EDIS 工具

最小实现，零外部依赖（仅 Python 标准库 http.server）。
生产环境可替换为 FastAPI / Flask。

端点:
  POST /tools/{name}  — 调用指定工具
  GET  /tools          — 列出所有工具
  GET  /health         — 健康检查
"""

import json
import sys
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))


class ToolHTTPHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理 — 路由到 AgentToolRegistry"""

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self._json(200, {"ok": True, "data": "EDIS Agent API v1"})

        elif path == "/tools":
            from agent import AgentToolRegistry
            self._json(200, AgentToolRegistry.list_all())

        else:
            self._json(404, {"ok": False, "error": {"code": "NOT_FOUND"}})

    def do_POST(self):
        path = urlparse(self.path).path

        # /tools/{name}
        if path.startswith("/tools/"):
            tool_name = path.split("/tools/")[1]
            if not tool_name:
                self._json(400, {"ok": False, "error": {"code": "BAD_REQUEST",
                                "message": "Missing tool name"}})
                return

            # Read body
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                params = json.loads(body)
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": {"code": "INVALID_JSON"}})
                return

            from agent import AgentToolRegistry
            result = AgentToolRegistry.run(tool_name, **params)
            status = 200 if result.ok else 400
            self._json(status, result.to_dict())

        else:
            self._json(404, {"ok": False, "error": {"code": "NOT_FOUND"}})

    def _json(self, status: int, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        self.wfile.flush()

    def log_message(self, format, *args):
        """Suppress default logging — use structured output instead"""
        pass


def run_server(host: str = "127.0.0.1", port: int = 8765):
    """启动 HTTP Tool Server"""
    server = HTTPServer((host, port), ToolHTTPHandler)
    print(f"EDIS Agent API: http://{host}:{port}")
    print(f"  Tools: GET  http://{host}:{port}/tools")
    print(f"  Call:  POST http://{host}:{port}/tools/{{name}}")
    print(f"  Health: GET http://{host}:{port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\nServer stopped.")


if __name__ == "__main__":
    run_server()

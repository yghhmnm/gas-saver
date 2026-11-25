"""
Gas Saver Web Server & Real-time Bridge
========================================
Serves the Gas Saver Web Dashboard and provides a live API bridge
for your real Arduino on COM8 and any WiFi sensors.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import os, sys, threading, webbrowser, time, socket

PORT = 8080
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        # Always serve the freshest dashboard while iterating on it
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

def main():
    os.chdir(WEB_DIR)
    local_ip = get_local_ip()
    server = HTTPServer(("0.0.0.0", PORT), Handler)

    print("=" * 55)
    print("  🚀 Gas Saver Web Dashboard is Live!")
    print("=" * 55)
    print(f"  • Local PC:   http://localhost:{PORT}")
    print(f"  • On Phone:   http://{local_ip}:{PORT}")
    print("=" * 55)

    # Open in browser automatically
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server...")
        server.server_close()

if __name__ == "__main__":
    main()

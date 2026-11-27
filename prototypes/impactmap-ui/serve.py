"""Loopback-only static UX prototype; no credentials or connector calls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    server = ThreadingHTTPServer(('127.0.0.1', 18087), partial(Handler, directory=str(root)))
    print('ImpactMap UX prototype: http://127.0.0.1:18087', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

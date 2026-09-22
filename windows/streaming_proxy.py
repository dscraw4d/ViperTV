from __future__ import annotations
import http.client
import http.server
import socketserver
import sys

LISTEN = int(sys.argv[1])
UPSTREAM = int(sys.argv[2])

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def _go(self):
        conn = http.client.HTTPConnection('127.0.0.1', UPSTREAM, timeout=60)
        headers = {k:v for k,v in self.headers.items() if k.lower() not in {'host','connection','proxy-connection','content-length'}}
        headers['Host'] = f'127.0.0.1:{UPSTREAM}'
        headers['X-Forwarded-Port'] = str(LISTEN)
        headers['X-Forwarded-Proto'] = 'http'
        length = int(self.headers.get('Content-Length','0') or 0)
        body = self.rfile.read(length) if length else None
        conn.request(self.command, self.path, body=body, headers=headers)
        r = conn.getresponse()
        self.send_response(r.status, r.reason)
        for k,v in r.getheaders():
            if k.lower() in {'transfer-encoding','connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailers','upgrade'}:
                continue
            self.send_header(k,v)
        self.send_header('Connection','close')
        self.end_headers()
        try:
            while True:
                chunk = r.read(65536)
                if not chunk: break
                self.wfile.write(chunk); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()
    do_GET = _go
    do_HEAD = _go
    do_POST = _go
    do_PUT = _go
    do_PATCH = _go
    do_DELETE = _go
    def log_message(self, fmt, *args):
        sys.stdout.write((fmt % args) + '\n'); sys.stdout.flush()

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

Server(('0.0.0.0', LISTEN), Handler).serve_forever()

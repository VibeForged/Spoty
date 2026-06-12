import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Spoty Bot is alive and running!")

    def log_message(self, format, *args):
        # Disable logging to avoid cluttering bot logs
        pass

def run():
    server = HTTPServer(('0.0.0.0', 7860), RequestHandler)
    server.serve_forever()

def keep_alive():
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import callback


def test_callbacks_reuse_connections_and_preserve_retries(monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            requests.append((self.client_address, self.headers.get('x-callback-token'), body))
            code = 503 if len(requests) == 1 else 200
            self.send_response(code)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(callback, '_callback_clients', threading.local())
    try:
        url = f'http://127.0.0.1:{server.server_port}/get-results'
        ok, detail = callback.post_step_callback(callback_url=url, callback_token='test-token', payload={'event_id':'same'}, retry_delays_sec=[0])
        assert ok and '2 attempt(s)' in detail
        assert callback._post_once(callback_url=url, callback_token='test-token', payload={'event_id':'next'}, timeout_sec=2)[0]
        assert len({request[0] for request in requests}) == 1
        assert requests[0][2] == requests[1][2]
        assert all(request[1] == 'test-token' for request in requests)
        # Log streaming has its own pool, so a slow log callback cannot hold
        # the stage callback connection.
        clients = []
        def other_thread():
            client = callback._callback_client()
            clients.append(client)
            client.close()
        worker = threading.Thread(target=other_thread)
        worker.start(); worker.join()
        assert clients[0] is not callback._callback_client()
    finally:
        callback._callback_client().close()
        server.shutdown(); server.server_close(); thread.join()


def test_empty_retry_schedule_means_one_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(callback, '_post_once', lambda **kwargs: (calls.append(kwargs) or False, 'failed'))
    ok, _ = callback.post_step_callback(callback_url='http://backend', callback_token='', payload={}, retry_delays_sec=[])
    assert not ok and len(calls) == 1

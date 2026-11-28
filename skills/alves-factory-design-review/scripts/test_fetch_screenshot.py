"""Run with: python -m unittest discover <this-dir>"""

import io
import struct
import tempfile
import threading
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fetch_screenshot


def png(width, height):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return fetch_screenshot.PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


BODIES = {"/shot.png": png(3, 2), "/page.html": b"<html>expired</html>"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = BODIES.get(self.path)
        self.send_response(200 if body else 404)
        self.end_headers()
        self.wfile.write(body or b"")

    def log_message(self, *args):
        pass


class Fetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "screens" / "A" / "desktop.png"

    def tearDown(self):
        self.tmp.cleanup()

    def main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = fetch_screenshot.main(list(args))
        return code, out.getvalue().strip(), err.getvalue().strip()

    def test_saves_the_png_and_reports_its_size(self):
        code, out, _ = self.main(f"{self.base}/shot.png", str(self.out))
        self.assertEqual((code, out), (0, f"{self.out} 3x2"))
        self.assertEqual(self.out.read_bytes(), BODIES["/shot.png"])

    def test_a_non_png_response_leaves_no_file(self):
        code, _, err = self.main(f"{self.base}/page.html", str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("did not return a PNG", err)
        self.assertFalse(self.out.exists())

    def test_an_http_error_exits_1(self):
        code, _, err = self.main(f"{self.base}/missing.png", str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("404", err)

    def test_only_http_urls(self):
        self.assertEqual(self.main("file:///etc/passwd", str(self.out))[0], 1)

    def test_png_size_rejects_other_bytes(self):
        self.assertIsNone(fetch_screenshot.png_size(b"GIF89a" + b"\x00" * 30))
        self.assertEqual(fetch_screenshot.png_size(png(1440, 900)), (1440, 900))


if __name__ == "__main__":
    unittest.main()

"""Save a Figma screenshot URL as a PNG file and read it back.

Usage:
    python fetch_screenshot.py <url> <out.png>

get_screenshot returns a short-lived URL to a PNG. This downloads it to <out.png>
(creating parent directories), then reads the file back and checks it is a PNG.
Prints "<out.png> <width>x<height>" and exits 0, or prints the problem on stderr
and exits 1, leaving no file behind.
"""

import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data):
    """(width, height) from a PNG's IHDR chunk, or None when the bytes are not a PNG."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def fetch(url, out, timeout=60):
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"not an http(s) URL: {url}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        error.close()
        raise
    if png_size(data) is None:
        raise ValueError(f"the URL did not return a PNG ({len(data)} bytes)")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".part")
    partial.write_bytes(data)
    partial.replace(out)
    size = png_size(out.read_bytes())
    if size is None:
        out.unlink(missing_ok=True)
        raise ValueError(f"{out} did not read back as a PNG")
    return size


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python fetch_screenshot.py <url> <out.png>", file=sys.stderr)
        return 1
    url, out = argv
    try:
        width, height = fetch(url, out)
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"{out} {width}x{height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

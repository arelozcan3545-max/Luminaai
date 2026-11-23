"""Serve only the Lumina browser assets on the local interface."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

ASSETS = ("index.html", "app.js", "config.js", "sw.js", "location_ui.js",
          "voice_engine.js", "citation_ui.js", "purify.min.js", "studio-preview.webp")

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    with TemporaryDirectory() as public:
        for name in ASSETS:
            source = root / name
            if source.is_file():
                copyfile(source, Path(public) / name)
        handler = partial(SimpleHTTPRequestHandler, directory=public)
        with ThreadingHTTPServer(("127.0.0.1", 5500), handler) as server:
            server.serve_forever()

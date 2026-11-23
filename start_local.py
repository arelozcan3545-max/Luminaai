"""Launch the local services from the Windows desktop shortcut."""
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://localhost:5500/index.html"
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ready(port):
    path = "/" if port == 8000 else "/index.html"
    try:
        with client.open(f"http://127.0.0.1:{port}{path}", timeout=1) as response:
            data = response.read(8192)
        if port == 8000:
            return json.loads(data).get("name") == "Lumina AI Engine"
        return b"<title>Lumina AI" in data
    except (OSError, ValueError, AttributeError):
        return False


def main():
    services = {
        8000: ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port",
               "8000", "--no-use-colors"],
        5500: ["serve_frontend.py"],
    }
    children = {}
    try:
        for port, args in services.items():
            if ready(port):
                print(f"{port}: Lumina zaten calisiyor.")
                continue
            print(f"{port}: Baslatiliyor...")
            children[port] = subprocess.Popen([sys.executable, *args], cwd=ROOT)
            deadline = time.monotonic() + 60
            while not ready(port):
                if children[port].poll() is not None:
                    raise RuntimeError(f"{port}: Sunucu kapandi. Yukaridaki hatayi kontrol edin.")
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"{port}: Sunucu 60 saniyede yanit vermedi.")
                time.sleep(0.3)
        print(f"Lumina hazir: {URL}")
        if "--check" in sys.argv:
            return
        webbrowser.open(URL)
        if children:
            print("Sunucular icin bu pencereyi acik tutun. Kapatmak icin Ctrl+C.")
        while children:
            for port, child in children.items():
                if child.poll() is not None:
                    raise RuntimeError(f"{port}: Sunucu durdu.")
            time.sleep(1)
    finally:
        for child in children.values():
            if child.poll() is None:
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                child.wait(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError) as exc:
        sys.exit(str(exc))

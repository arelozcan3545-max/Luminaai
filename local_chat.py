"""Keyless Qwen chat using the installed llama.cpp runner and shared GGUF."""
import atexit
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time

import requests

ROOT = Path(__file__).resolve().parent / ".models"
RUNNER = ROOT / "llama-vulkan/llama-server.exe"
if not RUNNER.is_file():
    RUNNER = ROOT / "llama/llama-server.exe"
WEIGHTS = ROOT / "z-image-turbo/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
_lock = threading.Lock()
_process = None
_address = None
_token = secrets.token_urlsafe(32)


def available():
    return RUNNER.is_file() and WEIGHTS.is_file()


def close():
    global _process
    if _process is not None and _process.poll() is None:
        _process.terminate()
        _process.wait(timeout=10)
    _process = None


atexit.register(close)


def _server():
    global _process, _address
    with _lock:
        if _process is not None and _process.poll() is None:
            return _address
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        _address = f"http://127.0.0.1:{port}"
        _process = subprocess.Popen(
            [str(RUNNER), "-m", str(WEIGHTS), "--host", "127.0.0.1", "--port", str(port),
             "--api-key", _token, "-c", "8192", "-t", "4", "-tb", "4", "-ngl", "99" if RUNNER.parent.name == "llama-vulkan" else "0",
             "--parallel", "1", "--sleep-idle-seconds", "5", "--cache-ram", "128"],
            cwd=RUNNER.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(180):
            if _process.poll() is not None:
                break
            try:
                if requests.get(_address + "/health", timeout=1).ok:
                    return _address
            except requests.RequestException:
                pass
            time.sleep(0.5)
        close()
        raise RuntimeError("Yerel sohbet motoru başlatılamadı.")


def stream(messages, max_tokens):
    endpoint = _server() + "/v1/chat/completions"
    with requests.post(endpoint, headers={"Authorization":"Bearer " + _token},
                       json={"model":"local", "messages":messages, "stream":True,
                             "max_tokens":min(max_tokens, 2048)}, timeout=(5, 180), stream=True) as response:
        response.raise_for_status()
        for line in response.iter_lines(chunk_size=1):
            if not line.startswith(b"data: "):
                continue
            data = line[6:]
            if data == b"[DONE]":
                break
            chunk = json.loads(data)["choices"][0]["delta"].get("content")
            if chunk:
                yield chunk

"""
One command to run the VN editor:

    python scripts/vn_editor/main.py

Opens the SSH tunnels to the VPS (Postgres, and Redis if asked), waits for them
to accept connections, then serves the editor and opens a browser at it. Any
tunnel that is already up is left alone, so this is safe to run alongside
tunnels you opened yourself.

    --no-tunnel     use whatever DATABASE_URL points at, open nothing
    --no-browser    do not open a browser window
    --redis         also tunnel Redis (the editor does not need it)
"""
import argparse
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import webbrowser

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

SSH_HOST = os.getenv("VN_SSH_HOST", "saguny@195.3.222.141")
SSH_KEY  = os.getenv("VN_SSH_KEY",  str(pathlib.Path.home() / ".ssh" / "id_ecdsa"))

TUNNELS = {
    "postgres": 5432,
    "redis":    6379,
}


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _open_tunnel(name: str, port: int) -> subprocess.Popen | None:
    if _port_open(port):
        print(f"[tunnel] {name} :{port} already open")
        return None

    cmd = ["ssh", "-N", "-L", f"{port}:localhost:{port}", SSH_HOST,
           "-o", "ServerAliveInterval=30", "-o", "ExitOnForwardFailure=yes"]
    if os.path.exists(SSH_KEY):
        cmd += ["-i", SSH_KEY]

    print(f"[tunnel] {name} :{port} opening")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for _ in range(60):
        if _port_open(port):
            print(f"[tunnel] {name} :{port} ready")
            return proc
        if proc.poll() is not None:
            err = (proc.stderr.read() or b"").decode(errors="replace").strip()
            raise SystemExit(f"[tunnel] {name} failed: {err or 'ssh exited'}")
        time.sleep(0.25)

    proc.terminate()
    raise SystemExit(f"[tunnel] {name} :{port} did not come up in 15s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tunnel",  action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--redis",      action="store_true")
    args = ap.parse_args()

    procs: list[subprocess.Popen] = []
    if not args.no_tunnel:
        wanted = ["postgres"] + (["redis"] if args.redis else [])
        for name in wanted:
            proc = _open_tunnel(name, TUNNELS[name])
            if proc:
                procs.append(proc)

    from scripts.vn_editor.config import DATABASE_URL, HOST, PORT
    from scripts.vn_editor.server import build_app
    from aiohttp import web

    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL (or VN_DATABASE_URL) is not set")

    url = f"http://{HOST}:{PORT}/vn"
    print(f"[vn-editor] {url}")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        web.run_app(build_app(), host=HOST, port=PORT, print=None)
    finally:
        for proc in procs:
            proc.terminate()
        if procs:
            print("[tunnel] closed")


if __name__ == "__main__":
    main()

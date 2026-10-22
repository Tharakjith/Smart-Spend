"""Local development launcher (no Docker needed).

1. starts an embedded PostgreSQL 16 (pgserver) under backend/var/pgdata, unless DATABASE_URL is set
2. applies Alembic migrations
3. optionally seeds demo data (DEMO_MODE=true)
4. runs the API on http://127.0.0.1:8000 and restarts it whenever a file under app/ or alembic/ changes

Auto-reload uses its own supervisor instead of `uvicorn --reload`. Uvicorn's reloader starts the server through
multiprocessing, which can hang on Windows (notably with Microsoft Store Python, whose venv launcher adds an
extra process). Here the server is a plain subprocess; on a change the whole process tree is killed, the port
is confirmed free, and a fresh server starts. Set DEV_RELOAD=false to disable.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # /T kills child processes too (the venv launcher spawns the real interpreter as a child).
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _start(cmd: list[str], env: dict, port: int) -> subprocess.Popen:
    deadline = time.monotonic() + 15
    while _port_open(port) and time.monotonic() < deadline:
        time.sleep(0.2)  # wait for the previous server to release the port
    if _port_open(port):
        print(f"[dev] port {port} is still in use by another process; stop it and save a file to retry", flush=True)
    return subprocess.Popen(cmd, cwd=ROOT, env=env)


def serve(cmd: list[str], env: dict, port: int, reload: bool) -> None:
    proc = _start(cmd, env, port)
    if not reload:
        try:
            proc.wait()
        except KeyboardInterrupt:
            _kill_tree(proc)
        return
    from watchfiles import PythonFilter, watch

    print("[dev] auto-reload on: watching app/ and alembic/", flush=True)
    try:
        for changes in watch(ROOT / "app", ROOT / "alembic", watch_filter=PythonFilter(), debounce=400, raise_interrupt=True):
            names = sorted({Path(p).relative_to(ROOT).as_posix() for _, p in changes})
            print(f"[dev] change detected in {', '.join(names[:3])}{' …' if len(names) > 3 else ''}; restarting API", flush=True)
            _kill_tree(proc)
            if any(n.startswith("alembic/versions/") for n in names):
                # Not applied automatically: a freshly generated migration is usually still being edited.
                print("[dev] migration files changed: run `python -m alembic upgrade head` when ready", flush=True)
            proc = _start(cmd, env, port)
    except KeyboardInterrupt:
        pass
    finally:
        _kill_tree(proc)


def main() -> None:
    env = os.environ.copy()
    env.setdefault("ENVIRONMENT", "development")
    env.setdefault("REQUIRE_EMAIL_VERIFICATION", "false")
    # Local only: the browser test suite signs up a dozen accounts a minute. Production keeps the strict default (10).
    env.setdefault("RATE_LIMIT_AUTH_PER_MINUTE", "120")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if not env.get("DATABASE_URL"):
        from scripts.devdb import ensure

        env["DATABASE_URL"] = ensure("smartspend")
    print(f"Database: {env['DATABASE_URL']}", flush=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
    if env.get("DEMO_MODE", "").lower() == "true":
        subprocess.run([sys.executable, "-m", "scripts.seed_demo"], cwd=ROOT, env=env, check=True)
    port = int(env.get("PORT", "8000"))
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    serve(cmd, env, port, reload=env.get("DEV_RELOAD", "true").lower() != "false")


if __name__ == "__main__":
    main()

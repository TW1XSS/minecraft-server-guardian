from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import tarfile
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "Minecraft Server Guardian"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Config:
    server_dir: Path
    start_command: str
    backup_dir: Path
    backup_interval_minutes: int = 30
    restart_delay_seconds: int = 10
    max_restart_attempts: int = 5
    discord_webhook_url: str = ""
    health_port: int = 8080
    log_lines: int = 200

    @classmethod
    def from_env(cls) -> "Config":
        server_dir = Path(os.getenv("SERVER_DIR", "/server")).resolve()
        backup_dir = Path(os.getenv("BACKUP_DIR", str(server_dir / "backups"))).resolve()
        return cls(
            server_dir=server_dir,
            start_command=os.getenv("START_COMMAND", "java -Xms1G -Xmx2G -jar server.jar nogui"),
            backup_dir=backup_dir,
            backup_interval_minutes=max(1, int(os.getenv("BACKUP_INTERVAL_MINUTES", "30"))),
            restart_delay_seconds=max(0, int(os.getenv("RESTART_DELAY_SECONDS", "10"))),
            max_restart_attempts=max(1, int(os.getenv("MAX_RESTART_ATTEMPTS", "5"))),
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
            health_port=max(1, int(os.getenv("HEALTH_PORT", "8080"))),
            log_lines=max(20, int(os.getenv("LOG_LINES", "200"))),
        )


class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, description: str, level: str = "info") -> None:
        if not self.webhook_url:
            return
        payload = {
            "username": "Server Guardian",
            "embeds": [
                {
                    "title": title,
                    "description": description[:3900],
                    "timestamp": utc_now(),
                    "footer": {"text": "Minecraft Server Guardian"},
                }
            ],
        }
        try:
            import urllib.request

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "minecraft-server-guardian"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:  # notification must never kill the guardian
            print(f"[guardian] discord notification failed: {exc}", flush=True)


class ServerGuardian:
    TPS_RE = re.compile(r"\bTPS\s*[:=]\s*(?P<tps>\d+(?:\.\d+)?)", re.I)
    MSPT_RE = re.compile(r"\bMSPT\s*[:=]\s*(?P<mspt>\d+(?:\.\d+)?)", re.I)
    PLAYER_RE = re.compile(r"\b(?:players?|online)\s*[:=]\s*(?P<count>\d+)", re.I)

    def __init__(self, config: Config):
        self.config = config
        self.notifier = DiscordNotifier(config.discord_webhook_url)
        self.process: Optional[subprocess.Popen[str]] = None
        self.started_at: Optional[float] = None
        self.last_exit_code: Optional[int] = None
        self.restart_count = 0
        self.total_restarts = 0
        self.last_restart_at: Optional[str] = None
        self.last_backup_at: Optional[str] = None
        self.last_backup_path: Optional[str] = None
        self.last_error: Optional[str] = None
        self.tps: Optional[float] = None
        self.mspt: Optional[float] = None
        self.players: Optional[int] = None
        self.log_buffer: deque[str] = deque(maxlen=config.log_lines)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._monitor_loop, daemon=True)
        self._backup_worker = threading.Thread(target=self._backup_loop, daemon=True)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        self.config.server_dir.mkdir(parents=True, exist_ok=True)
        self.config.backup_dir.mkdir(parents=True, exist_ok=True)
        if not self.running:
            self._launch(initial=True)
        self._worker.start()
        self._backup_worker.start()

    def stop(self) -> None:
        self._stop.set()
        proc = self.process
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=15)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _launch(self, initial: bool = False) -> None:
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        print(f"[guardian] starting: {self.config.start_command}", flush=True)
        try:
            proc = subprocess.Popen(
                self.config.start_command,
                cwd=self.config.server_dir,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,
            )
        except Exception as exc:
            self.last_error = f"Could not start server: {exc}"
            self.notifier.send("🔴 Server start failed", self.last_error, "error")
            raise
        with self._lock:
            self.process = proc
            self.started_at = time.time()
            self.last_exit_code = None
            self.restart_count = self.restart_count if not initial else 0
            self.last_error = None
        threading.Thread(target=self._read_output, args=(proc,), daemon=True).start()
        if initial:
            self.notifier.send("🟢 Server Guardian started", "Minecraft server process is being monitored.")
        else:
            self.notifier.send("🟢 Minecraft server restarted", f"Restart #{self.total_restarts} completed.")

    def _read_output(self, proc: subprocess.Popen[str]) -> None:
        if not proc.stdout:
            return
        for line in proc.stdout:
            line = line.rstrip("\n")
            self.log_buffer.append(line)
            self._parse_metrics(line)
            if "Exception" in line or "ERROR" in line or "OutOfMemory" in line:
                self.last_error = line[-1000:]
        proc.stdout.close()

    def _parse_metrics(self, line: str) -> None:
        match = self.TPS_RE.search(line)
        if match:
            self.tps = float(match.group("tps"))
        match = self.MSPT_RE.search(line)
        if match:
            self.mspt = float(match.group("mspt"))
        match = self.PLAYER_RE.search(line)
        if match:
            self.players = int(match.group("count"))

    def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            proc = self.process
            if proc is not None:
                code = proc.poll()
                if code is not None:
                    with self._lock:
                        self.last_exit_code = code
                        self.process = None
                    if self._stop.is_set():
                        break
                    self.restart_count += 1
                    self.total_restarts += 1
                    self.last_restart_at = utc_now()
                    msg = f"Process exited with code {code}. Automatic restart #{self.total_restarts} is scheduled."
                    recent = "\n".join(list(self.log_buffer)[-20:])
                    self.notifier.send("🔴 Minecraft server stopped", f"{msg}\n\n```text\n{recent[-2800:]}\n```", "error")
                    if self.restart_count >= self.config.max_restart_attempts:
                        self.last_error = "Maximum automatic restart attempts reached. Manual intervention required."
                        self.notifier.send("🛑 Auto-restart paused", self.last_error, "error")
                        break
                    time.sleep(self.config.restart_delay_seconds)
                    self._launch()
            time.sleep(2)

    def _backup_loop(self) -> None:
        while not self._stop.is_set():
            self.create_backup()
            self._stop.wait(self.config.backup_interval_minutes * 60)

    def create_backup(self) -> Optional[Path]:
        self.config.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.config.backup_dir / f"server-{stamp}.tar.gz"
        temp = target.with_suffix(target.suffix + ".tmp")
        try:
            excluded_root = self.config.backup_dir.resolve()
            with tarfile.open(temp, "w:gz") as archive:
                for item in self.config.server_dir.iterdir():
                    try:
                        if item.resolve() == excluded_root or excluded_root in item.resolve().parents:
                            continue
                        archive.add(item, arcname=item.name, recursive=True)
                    except FileNotFoundError:
                        continue
            temp.replace(target)
            with self._lock:
                self.last_backup_at = utc_now()
                self.last_backup_path = str(target)
            print(f"[guardian] backup created: {target}", flush=True)
            return target
        except Exception as exc:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
            self.last_error = f"Backup failed: {exc}"
            self.notifier.send("⚠️ Backup failed", self.last_error, "warning")
            return None

    def status(self) -> dict:
        with self._lock:
            return {
                "name": APP_NAME,
                "running": self.running,
                "pid": self.process.pid if self.process else None,
                "started_at": datetime.fromtimestamp(self.started_at, timezone.utc).isoformat() if self.started_at else None,
                "last_exit_code": self.last_exit_code,
                "restart_count": self.restart_count,
                "total_restarts": self.total_restarts,
                "last_restart_at": self.last_restart_at,
                "last_backup_at": self.last_backup_at,
                "last_backup_path": self.last_backup_path,
                "tps": self.tps,
                "mspt": self.mspt,
                "players": self.players,
                "last_error": self.last_error,
                "server_dir": str(self.config.server_dir),
            }

    def recent_logs(self) -> list[str]:
        return list(self.log_buffer)[-100:]


g = ServerGuardian(Config.from_env())


INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Minecraft Server Guardian</title>
<style>
body{font-family:Inter,system-ui,sans-serif;background:#0b0f14;color:#e9eef5;max-width:1100px;margin:0 auto;padding:32px}h1{margin:0 0 6px}.muted{color:#97a3b2}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:24px 0}.card{background:#111823;border:1px solid #202a38;border-radius:14px;padding:18px}.value{font-size:28px;font-weight:700;margin-top:8px}.ok{color:#6ee7a8}.bad{color:#ff7b7b}pre{background:#070b10;border:1px solid #202a38;padding:16px;border-radius:12px;overflow:auto;max-height:500px}button{padding:10px 14px;border-radius:10px;border:1px solid #2d394a;background:#182231;color:#e9eef5;cursor:pointer}
</style></head><body><h1>🛡️ Minecraft Server Guardian</h1><div class="muted">Crash recovery · backups · Discord alerts · tiny web dashboard</div>
<div class="grid"><div class="card"><div class="muted">Status</div><div id="status" class="value">Loading…</div></div><div class="card"><div class="muted">Players</div><div id="players" class="value">—</div></div><div class="card"><div class="muted">TPS</div><div id="tps" class="value">—</div></div><div class="card"><div class="muted">MSPT</div><div id="mspt" class="value">—</div></div><div class="card"><div class="muted">Restarts</div><div id="restarts" class="value">—</div></div></div>
<div class="card"><button onclick="backup()">Create backup now</button><span id="backupResult" class="muted"></span></div><br>
<div class="card"><div class="muted">Recent logs</div><pre id="logs">Loading…</pre></div>
<script>
async function refresh(){const s=await (await fetch('/api/status')).json(); document.querySelector('#status').innerHTML=s.running?'<span class="ok">● RUNNING</span>':'<span class="bad">● STOPPED</span>'; document.querySelector('#players').textContent=s.players??'—'; document.querySelector('#tps').textContent=s.tps??'—'; document.querySelector('#mspt').textContent=s.mspt??'—'; document.querySelector('#restarts').textContent=s.total_restarts; const l=await (await fetch('/api/logs')).json(); document.querySelector('#logs').textContent=l.logs.join('\\n');} 
async function backup(){const r=await fetch('/api/backup',{method:'POST'}); const j=await r.json(); document.querySelector('#backupResult').textContent=j.ok?' Backup created.':' Backup failed: '+j.error;}
refresh(); setInterval(refresh,3000);
</script></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    guardian: ServerGuardian | None = None

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if not self.guardian:
            return self._send(503, "text/plain; charset=utf-8", b"Guardian not ready")
        if self.path == "/":
            return self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode())
        if self.path == "/api/status":
            return self._send(200, "application/json; charset=utf-8", json.dumps(self.guardian.status()).encode())
        if self.path == "/api/logs":
            return self._send(200, "application/json; charset=utf-8", json.dumps({"logs": self.guardian.recent_logs()}).encode())
        self._send(404, "application/json; charset=utf-8", b'{"error":"not found"}')

    def do_POST(self):  # noqa: N802
        if not self.guardian:
            return self._send(503, "application/json; charset=utf-8", b'{"error":"not ready"}')
        if self.path == "/api/backup":
            path = self.guardian.create_backup()
            if path is None:
                return self._send(500, "application/json; charset=utf-8", json.dumps({"ok": False, "error": self.guardian.last_error}).encode())
            return self._send(200, "application/json; charset=utf-8", json.dumps({"ok": True, "path": str(path)}).encode())
        self._send(404, "application/json; charset=utf-8", b'{"error":"not found"}')

    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} - {fmt % args}", flush=True)


def main() -> None:
    g.start()
    DashboardHandler.guardian = g
    server = ThreadingHTTPServer(("0.0.0.0", g.config.health_port), DashboardHandler)
    print(f"[guardian] dashboard listening on :{g.config.health_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        g.stop()


if __name__ == "__main__":
    main()

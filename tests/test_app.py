import tempfile
import time
from pathlib import Path

from guardian.app import Config, ServerGuardian


def make_guardian(tmp: Path) -> ServerGuardian:
    cfg = Config(
        server_dir=tmp / "server",
        start_command="python -c \"import time; print('TPS=19.8 MSPT=42.1 players=3', flush=True); time.sleep(60)\"",
        backup_dir=tmp / "backups",
    )
    return ServerGuardian(cfg)


def test_metrics_and_status(tmp_path):
    g = make_guardian(tmp_path)
    g._parse_metrics("TPS=19.8 MSPT=42.1 players=3")
    s = g.status()
    assert s["tps"] == 19.8
    assert s["mspt"] == 42.1
    assert s["players"] == 3


def test_backup(tmp_path):
    g = make_guardian(tmp_path)
    g.config.server_dir.mkdir(parents=True)
    (g.config.server_dir / "level.dat").write_text("demo")
    result = g.create_backup()
    assert result is not None
    assert result.exists()


def test_recent_logs(tmp_path):
    g = make_guardian(tmp_path)
    g.log_buffer.extend(["a", "b", "c"])
    assert g.recent_logs() == ["a", "b", "c"]

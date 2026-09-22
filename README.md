# 🛡️ Minecraft Server Guardian

> 24/7 Minecraft server monitoring, crash recovery, backups and Discord alerts — self-hosted and Docker-first.

[![CI](https://github.com/TW1XSS/minecraft-server-guardian/actions/workflows/ci.yml/badge.svg)](https://github.com/TW1XSS/minecraft-server-guardian/actions/workflows/ci.yml)

Minecraft servers die at the worst possible time. **Server Guardian** watches the server process, captures its output, automatically restarts it after a crash, creates rolling tar.gz backups, and exposes a tiny dashboard.

## What you get

- 🔄 Automatic restart after process crashes
- 💾 Scheduled backups
- 📣 Discord webhook alerts
- 📊 Tiny web dashboard (`:8080`)
- 📝 Recent log viewer
- 🐳 Docker Compose deployment
- 🧩 Environment-variable configuration
- 🪶 No database and no external SaaS dependency

## Quick start

1. Put your Minecraft server files in `./server/`.
2. Copy `.env.example` to `.env` and adjust values.
3. Start Guardian:

```bash
docker compose up -d --build
```

4. Open `http://localhost:8080`.

The runtime has no third-party Python dependencies; the Docker image runs only the Python standard library.

### Start command

By default Guardian runs:

```text
java -Xms1G -Xmx2G -jar server.jar nogui
```

Change `START_COMMAND` for your Paper/Spigot/Fabric setup.

## Discord

Create a Discord webhook and put it into `DISCORD_WEBHOOK_URL`.

Guardian sends alerts when:

- the server starts,
- the server crashes/stops,
- an automatic restart happens,
- the restart limit is reached,
- a backup fails.

## Demo without Minecraft

You can test crash recovery locally with the included mock process:

```bash
python demo/mock_server.py
```

Then run Guardian with:

```bash
SERVER_DIR=./demo/server \\
START_COMMAND="python ../mock_server.py --crash-after 8" \\
BACKUP_INTERVAL_MINUTES=60 \\
python -m guardian.app
```

The mock process exits intentionally. Guardian should detect the exit and restart it.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SERVER_DIR` | `/server` | Minecraft server directory |
| `START_COMMAND` | Java command | Command used to launch the server |
| `BACKUP_DIR` | `/server/backups` | Backup destination |
| `BACKUP_INTERVAL_MINUTES` | `30` | Backup interval |
| `RESTART_DELAY_SECONDS` | `10` | Delay before restart |
| `MAX_RESTART_ATTEMPTS` | `5` | Consecutive crash restart cap |
| `HEALTH_PORT` | `8080` | Dashboard/API port |
| `DISCORD_WEBHOOK_URL` | empty | Optional Discord webhook |

## API

```text
GET  /api/status
GET  /api/logs
POST /api/backup
```

## Roadmap

- [ ] Paper plugin for reliable TPS/MSPT metrics
- [ ] RCON command endpoint with authentication
- [ ] Telegram notifications
- [ ] Multi-server dashboard
- [ ] Retention policies for backups
- [ ] Crash-report fingerprinting
- [ ] Prometheus metrics

## Contributing

Issues and pull requests are welcome. Keep the core dependency-free where practical and prefer small, composable features.

## License

MIT.

# Security

Server Guardian is intentionally small, but the dashboard is not an authentication system.

## Before exposing the dashboard to the internet

- Put it behind a reverse proxy or private network.
- Add authentication at the proxy layer.
- Do not expose the Docker socket.
- Treat the Minecraft server directory as trusted input.
- Keep Discord webhook URLs private.

Report security issues privately to the repository owner rather than opening a public issue with exploit details.

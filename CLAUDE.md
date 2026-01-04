# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based REST API for remote management of an AI equipment running Ollama. It provides Wake-on-LAN capabilities to power on the machine, SSH-based shutdown, and status checks to verify if both the machine and Ollama service are online.

## Architecture

### Single-File Application
The entire API is contained in `main.py` (163 lines). There are no separate modules, routers, or service layers - all functionality is implemented directly in the main file.

### Core Components
- **Authentication**: API key validation via `X-API-Key` header using FastAPI's `APIKeyHeader` security
- **Status Checking**: Uses OS-specific ping commands (via subprocess) + HTTP request to Ollama's `/api/tags` endpoint
- **Wake-on-LAN**: Uses `wakeonlan` library to send magic packets
- **SSH Shutdown**: Uses `paramiko` to execute `sudo shutdown -h now` on the remote machine

### Key Endpoints
- `GET /` - Public endpoint, no auth required
- `GET /test` - Checks if equipment is online (ping) and if Ollama responds
- `POST /arrancar` - Sends WOL magic packet to start the machine
- `POST /apagar` - Connects via SSH and executes shutdown command

### Environment Configuration
All configuration loaded from `.env` file:
- `EQUIPO_IA` - IP address of the AI machine
- `IA_MAC` - MAC address for Wake-on-LAN
- `OLLAMA_PORT` - Ollama service port (default 11434)
- `SSH_USER`, `SSH_PASS`, `SSH_PORT` - SSH credentials
- `API_KEYS` - Comma-separated list of valid API keys
- `SUBDOMINIO` - Used by Docker/Traefik for routing

## Development Commands

### Local Development (without Docker)
```bash
pip install -r requirements.txt
python main.py
```
The API runs on `http://localhost:8000`

### Docker Development
```bash
# Build and run
docker-compose up -d --build

# View logs
docker-compose logs -f antoni-ia-api

# Stop
docker-compose down
```

### API Documentation
Once running, access auto-generated docs:
- Swagger UI: `/docs`
- ReDoc: `/redoc`

## Important Implementation Notes

### SSH Shutdown Requirements
The `/apagar` endpoint requires:
- SSH user must have sudo permissions for shutdown command
- Sudo should be configured without password prompt for shutdown
- Setup on target machine: `echo "usuario ALL=(ALL) NOPASSWD: /sbin/shutdown" | sudo tee /etc/sudoers.d/shutdown`

### Platform-Specific Ping Commands
The `/test` endpoint uses different ping commands based on OS:
- Windows: `ping -n 1 -w 1000 {IP}`
- Linux/Mac: `ping -c 1 -W 1 {IP}`

This is detected via `os.name == 'nt'` in main.py:72-83

### Docker Deployment
The project is designed to work with Traefik reverse proxy:
- Expects external network named `traefik`
- Uses Let's Encrypt for SSL certificates (certresolver=letsencrypt)
- Container exposes port 8000 internally
- Traefik routing based on `SUBDOMINIO` environment variable

### Async Operations
The API uses async/await pattern:
- Ping operations use `asyncio.create_subprocess_shell`
- HTTP requests to Ollama use `httpx.AsyncClient`
- SSH operations (paramiko) are synchronous but wrapped in async endpoints

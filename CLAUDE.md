# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based REST API for remote management of an AI equipment running Ollama. It provides Wake-on-LAN capabilities to power on the machine, SSH-based shutdown, and status checks to verify if both the machine and Ollama service are online.

## Architecture

### Single-File Application
The entire API is contained in `main.py` (397 lines). There are no separate modules, routers, or service layers - all functionality is implemented directly in the main file.

### Core Components
- **Authentication**: API key validation via `X-API-Key` header using FastAPI's `APIKeyHeader` security
- **Status Checking**: TCP socket connection to SSH port + HTTP request to Ollama's `/api/tags` endpoint (replaced ping-based approach in main.py:45-65)
- **Wake-on-LAN**: Uses `wakeonlan` library to send magic packets to broadcast address
- **SSH Shutdown**: Uses `paramiko` to execute `sudo shutdown -h now` on the remote machine with sudo password support

### Key Endpoints
- `GET /` - Public endpoint, no auth required (main.py:91-97)
- `GET /debug` - Debug diagnostics for connectivity issues, requires auth (main.py:100-151)
- `GET /test` - Checks if equipment is online (TCP connection) and if Ollama responds (main.py:154-197)
- `GET /lista_modelos` - Lists all Ollama models installed on the remote machine (main.py:200-262)
- `POST /arrancar` - Sends WOL magic packet to start the machine, checks if already running first (main.py:265-292)
- `POST /apagar` - Connects via SSH and executes shutdown command, checks if already off first (main.py:295-391)

### Environment Configuration
All configuration loaded from `.env` file:
- `EQUIPO_IA` - IP address of the AI machine
- `IA_MAC` - MAC address for Wake-on-LAN
- `OLLAMA_PORT` - Ollama service port (default 11434)
- `SSH_USER`, `SSH_PASS`, `SSH_SUDO_PASS`, `SSH_PORT` - SSH credentials (SSH_SUDO_PASS defaults to SSH_PASS if not set)
- `WOL_BROADCAST` - Broadcast address for WOL packets (e.g., 192.168.1.255)
- `WOL_PORT` - Port for WOL packets (default 9)
- `API_KEYS` - Comma-separated list of valid API keys
- `SUBDOMINIO` - Used by Docker/Traefik for routing

## Development Commands

### Local Development (without Docker)
```bash
pip install -r requirements.txt
python main.py
```
The API runs on `http://localhost:8000`

### Production Deployment
```bash
# Automated deployment with git pull + build + network checks
./desplegar_docker.sh

# Manual deployment with Traefik + macvlan for WOL
docker-compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### API Documentation
Once running, access auto-generated docs:
- Swagger UI: `/docs`
- ReDoc: `/redoc`

## Important Implementation Notes

### Docker Networking Architecture
The project uses a dual-network configuration to support both Traefik routing and Wake-on-LAN:
- **proxy network**: External network connecting to Traefik for HTTPS routing
- **macvlan_local network**: External macvlan network for direct layer-2 access to send WOL packets

This allows the container to have two IPs: one for Traefik (HTTPS) and one for WOL broadcast packets.

Create the macvlan network once before first deployment:
```bash
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  --ip-range=192.168.1.240/28 \
  --aux-address="host=192.168.1.230" \
  -o parent=enp45s0 \
  macvlan_local
```

### SSH Shutdown Implementation
The `/apagar` endpoint (main.py:295-391) implements:
1. Pre-flight check to avoid unnecessary SSH connections if already off
2. Primary attempt: `sudo shutdown -h now` with password via stdin
3. Fallback attempt: `shutdown -h now` without sudo (if user has direct permissions)

Setup on target machine for passwordless sudo shutdown:
```bash
echo "usuario ALL=(ALL) NOPASSWD: /sbin/shutdown" | sudo tee /etc/sudoers.d/shutdown
```

### Connectivity Check Strategy
Replaced ping-based checks with TCP socket connection (main.py:45-65):
- Tests SSH port (default 22) with 2-second timeout
- More reliable than ICMP ping which may be blocked by firewalls
- Works across all platforms without subprocess overhead

### Wake-on-LAN Configuration
The `/arrancar` endpoint (main.py:265-292) sends WOL packets to the broadcast address specified in `WOL_BROADCAST`. The macvlan network is critical for this to work from Docker, as it provides direct layer-2 network access.

### Async Operations
The API uses async/await pattern:
- TCP connectivity checks use `asyncio.run_in_executor` with socket operations
- HTTP requests to Ollama use `httpx.AsyncClient`
- SSH operations (paramiko) are synchronous but wrapped in async endpoints

### Deployment Script
`desplegar_docker.sh` automates the full deployment workflow:
1. Updates repository via `git pull`
2. Verifies `proxy` network exists (creates if missing)
3. Verifies `macvlan_local` network exists (exits with instructions if missing)
4. Stops existing container
5. Builds and starts container with both docker-compose files
6. Displays status and helpful commands

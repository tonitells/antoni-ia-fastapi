# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based REST API for remote management of an AI equipment running Ollama. It provides Wake-on-LAN capabilities to power on the machine, SSH-based shutdown, status checks, model management, and a full proxy to Ollama's API endpoints.

## Architecture

### Single-File Application
The entire API is contained in `main.py` (~730 lines). There are no separate modules, routers, or service layers - all functionality is implemented directly in the main file.

### Core Components
- **Authentication**: API key validation via `X-API-Key` header using FastAPI's `APIKeyHeader` security. All endpoints except `GET /` require authentication.
- **Status Checking**: Uses TCP socket connectivity checks (via `check_host_connectivity()`) to verify if host is online, plus HTTP requests to Ollama's `/api/tags` endpoint
- **Wake-on-LAN**: Uses `wakeonlan` library to send magic packets with configurable broadcast address and port
- **SSH Shutdown**: Uses `paramiko` to execute `sudo shutdown -h now` on the remote machine, with fallback to non-sudo shutdown
- **Ollama Proxy**: Full proxy implementation for Ollama API endpoints (generate, chat, pull, delete, show) supporting both streaming and non-streaming responses

### Key Endpoints

#### Management Endpoints
- `GET /` - Public endpoint, no auth required
- `GET /debug` - Debug info for diagnostics (config, ping tests)
- `GET /test` - Checks if equipment is online (TCP check) and if Ollama responds
- `GET /lista_modelos` - Lists all installed Ollama models
- `POST /arrancar` - Sends WOL magic packet to start the machine (checks if already online first)
- `POST /apagar` - Connects via SSH and executes shutdown command (checks if already offline first)

#### Ollama Proxy Endpoints
All proxy endpoints check host connectivity before proxying to Ollama:
- `POST /ollama/generate` - Generate text completions (supports streaming)
- `POST /ollama/chat` - Chat completions (supports streaming)
- `POST /ollama/pull` - Download/pull models (supports streaming for progress)
- `POST /ollama/delete` - Delete models
- `POST /ollama/show` - Show model details

### Environment Configuration
All configuration loaded from `.env` file:
- `EQUIPO_IA` - IP address of the AI machine
- `IA_MAC` - MAC address for Wake-on-LAN
- `OLLAMA_PORT` - Ollama service port (default 11434)
- `SSH_USER`, `SSH_PASS`, `SSH_PORT` - SSH credentials
- `SSH_SUDO_PASS` - Sudo password (defaults to SSH_PASS if not set)
- `WOL_BROADCAST` - Broadcast address for WOL packets (default 255.255.255.255)
- `WOL_PORT` - Port for WOL packets (default 9)
- `API_KEYS` - Comma-separated list of valid API keys
- `SUBDOMINIO` - Domain used by Docker/Traefik for routing

## Development Commands

### Local Development (without Docker)
```bash
pip install -r requirements.txt
python main.py
```
The API runs on `http://localhost:8000`

### Docker Deployment

#### Automated Deployment (Recommended)
```bash
./desplegar_docker.sh
```
This script automates the full deployment process:
1. Updates repository with `git pull`
2. Verifies `proxy` and `macvlan_local` networks exist
3. Stops previous container
4. Builds and starts container with Traefik configuration
5. Shows container status and useful commands

#### Manual Docker Commands

**Option 1: Traefik + Wake-on-LAN (Production)**
```bash
# Build and run with Traefik
docker-compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build

# View logs
docker-compose logs -f antoni-ia-api

# Stop
docker-compose -f docker-compose.yml -f docker-compose.traefik.yml down
```
This requires:
- Network `proxy` (external, for Traefik)
- Network `macvlan_local` (external, for Wake-on-LAN)
- See README.md for macvlan setup instructions

**Option 2: Host Mode (Simple, no Traefik)**
```bash
# Build and run in host mode
docker-compose -f docker-compose.yml -f docker-compose.host.yml up -d --build

# View logs
docker-compose logs -f antoni-ia-api

# Stop
docker-compose -f docker-compose.yml -f docker-compose.host.yml down
```
This runs the container with `network_mode: host`:
- Wake-on-LAN works without special configuration
- API accessible at `http://HOST_IP:8000`
- Not compatible with Traefik

### API Documentation
Once running, access auto-generated docs:
- Swagger UI: `/docs`
- ReDoc: `/redoc`

## Important Implementation Notes

### Host Connectivity Checking
The application uses `check_host_connectivity()` (main.py:47-68) to verify if the remote host is online:
- Uses TCP socket connection attempts (default: port 22/SSH)
- Runs in asyncio executor to avoid blocking
- 2-second timeout by default
- This replaced earlier ping-based approaches for better reliability across platforms

The `/debug` endpoint still includes ping tests for diagnostics using platform-specific commands:
- Windows: `ping -n 1 -w 2000 {IP}`
- Linux/Mac: `ping -c 1 -W 2 {IP}`

### SSH Shutdown Implementation
The `/apagar` endpoint (main.py:335-432) has sophisticated shutdown logic:
1. First checks if host is already offline (via `check_host_connectivity`)
2. Attempts shutdown with sudo using `SSH_SUDO_PASS`: `echo "{SSH_SUDO_PASS}" | sudo -S shutdown -h now`
3. Falls back to non-sudo shutdown if sudo fails
4. Returns appropriate error messages if both methods fail

Requirements on target machine:
- SSH access with valid credentials
- User should have sudo permissions for shutdown, OR
- Configure passwordless sudo: `echo "usuario ALL=(ALL) NOPASSWD: /sbin/shutdown" | sudo tee /etc/sudoers.d/shutdown`

### Wake-on-LAN Configuration
The `/arrancar` endpoint (main.py:305-333):
- First checks if host is already online (via `check_host_connectivity`)
- Sends magic packet using `wakeonlan` library
- Uses configurable broadcast address (`WOL_BROADCAST`) and port (`WOL_PORT`)
- Only sends WOL packet if host is confirmed offline

Docker networking considerations:
- **Host mode** (`docker-compose.host.yml`): WOL works without special configuration
- **Bridge mode with Traefik** (`docker-compose.traefik.yml`): Requires macvlan network for direct layer-2 access

### Ollama Proxy Implementation
Proxy endpoints (main.py:434-726) implement full passthrough to Ollama:
- All endpoints verify host connectivity before proxying
- Support both streaming (`StreamingResponse`) and non-streaming responses
- Streaming uses `httpx.AsyncClient.stream()` with chunk iteration
- Generate/Chat: 300s timeout
- Pull: 3600s timeout (1 hour for large models)
- Delete/Show: 30s timeout
- Returns appropriate HTTP errors (503 if offline, 504 on timeout, 500 on other errors)

### Docker and Traefik Configuration
The project uses Docker Compose with overlay files:
- Base: `docker-compose.yml` (defines service, references external `proxy` network)
- Traefik overlay: `docker-compose.traefik.yml` (adds macvlan network, Traefik labels, ports)
- Host overlay: `docker-compose.host.yml` (sets `network_mode: host`)

Traefik configuration (in `docker-compose.traefik.yml`):
- Expects external network named `proxy` (not "traefik")
- Expects external network named `macvlan_local` for Wake-on-LAN
- Uses Let's Encrypt for SSL (`certresolver=letsencrypt`)
- HTTP to HTTPS redirect configured
- Routing based on `SUBDOMINIO` environment variable

### Async Operations
The API uses async/await throughout:
- Host connectivity checks use `asyncio.get_event_loop().run_in_executor()`
- HTTP requests to Ollama use `httpx.AsyncClient`
- SSH operations (paramiko) are synchronous but wrapped in async endpoint functions
- Ping commands (debug only) use `asyncio.create_subprocess_shell`

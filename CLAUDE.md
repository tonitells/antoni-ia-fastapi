# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based REST API for remote management of an AI equipment running Ollama. It provides Wake-on-LAN capabilities to power on the machine, SSH-based shutdown, status checks, model management, and a full proxy to Ollama's API endpoints.

## Architecture

### Single-File Application
The entire API is contained in `main.py` (~900 lines). There are no separate modules, routers, or service layers - all functionality is implemented directly in the main file.

### Core Components
- **Authentication**: API key validation via `X-API-Key` header using FastAPI's `APIKeyHeader` security. All endpoints except `GET /` require authentication.
- **Status Management**: Persistent state tracking with `status.json` file managing equipment state, request counters, and operational modes
- **Status Checking**: Uses TCP socket connectivity checks (via `check_host_connectivity()`) to verify if host is online, plus HTTP requests to Ollama's `/api/tags` endpoint
- **Wake-on-LAN**: Uses `wakeonlan` library to send magic packets with configurable broadcast address and port
- **SSH Shutdown**: Uses `paramiko` to execute `sudo shutdown -h now` on the remote machine, with fallback to non-sudo shutdown
- **Ollama Proxy**: Full proxy implementation for Ollama API endpoints (generate, chat, pull, delete, show) supporting both streaming and non-streaming responses

### Key Endpoints

#### Management Endpoints
- `GET /` - Public endpoint, no auth required
- `GET /debug` - Debug info for diagnostics (config, ping tests)
- `GET /test` - Checks if equipment is online (TCP check) and if Ollama responds, updates status
- `GET /status` - Returns current system status from status.json
- `POST /init` - Initialize system state based on real equipment verification
- `GET /lista_modelos` - Lists all installed Ollama models
- `POST /arrancar` - Sends WOL magic packet to start the machine, increments request counter
- `POST /apagar` - Conditional shutdown based on request counter and permanent mode
- `POST /permanent_on_enable` - Activate permanent mode (prevents automatic shutdown)
- `POST /permanent_on_disable` - Deactivate permanent mode
- `POST /shutdown` - Forced shutdown with complete state reset

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
- `WOL_BROADCAST` - Broadcast address for WOL packets (e.g., 192.168.1.255)
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

### Testing
```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest test_main.py -v

# Run specific test class
pytest test_main.py::TestArrancarEndpoint -v

# Run with coverage
pytest test_main.py --cov=main --cov-report=html
```
See TESTING.md for comprehensive testing documentation.

### Production Deployment

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

#### Manual Deployment
```bash
# Build and run with Traefik + macvlan for WOL
docker-compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose -f docker-compose.yml -f docker-compose.traefik.yml down
```
This requires:
- Network `proxy` (external, for Traefik)
- Network `macvlan_local` (external, for Wake-on-LAN)
- See README.md for macvlan setup instructions

### API Documentation
Once running, access auto-generated docs:
- Swagger UI: `/docs`
- ReDoc: `/redoc`

## Important Implementation Notes

### Status Management System
The application uses a persistent state file (`status/status.json`) to track:
- `logical_on`: True if Ollama is responding
- `phisical_on`: True if equipment is online (TCP connection)
- `peticions_ollama`: Counter of active requests (incremented by /arrancar, decremented by /apagar)
- `permanent_on`: Flag to prevent automatic shutdown
- `message`: Last operation message
- `datetime`: Last update timestamp

Functions for state management:
- `read_status()`: Reads current state, creates from base.json if missing
- `write_status()`: Writes state with automatic timestamp update
- `update_status()`: Updates specific fields with message

### Host Connectivity Checking
The application uses `check_host_connectivity()` to verify if the remote host is online:
- Uses TCP socket connection attempts (default: port 22/SSH)
- Runs in asyncio executor to avoid blocking
- 2-second timeout by default
- This replaced earlier ping-based approaches for better reliability across platforms

The `/debug` endpoint still includes ping tests for diagnostics using platform-specific commands:
- Windows: `ping -n 1 -w 2000 {IP}`
- Linux/Mac: `ping -c 1 -W 2 {IP}`

### SSH Shutdown Implementation
The `/apagar` endpoint has sophisticated conditional shutdown logic:
1. First checks if host is already offline (via `check_host_connectivity`)
2. Decrements `peticions_ollama` counter (minimum 0)
3. Determines if physical shutdown should occur:
   - Shutdown only if `peticions_ollama < 1` AND `permanent_on = false`
4. If shutdown approved:
   - Attempts shutdown with sudo: `echo "{SSH_SUDO_PASS}" | sudo -S shutdown -h now`
   - Falls back to non-sudo shutdown if sudo fails
5. Updates state accordingly

Requirements on target machine:
- SSH access with valid credentials
- User should have sudo permissions for shutdown, OR
- Configure passwordless sudo: `echo "usuario ALL=(ALL) NOPASSWD: /sbin/shutdown" | sudo tee /etc/sudoers.d/shutdown`

### Wake-on-LAN Configuration
The `/arrancar` endpoint:
- First checks if host is already online (via `check_host_connectivity`)
- Increments `peticions_ollama` counter
- Sends magic packet using `wakeonlan` library
- Uses configurable broadcast address (`WOL_BROADCAST`) and port (`WOL_PORT`)

Docker networking considerations:
- Requires macvlan network for direct layer-2 access to send WOL packets
- Container has two IPs: one for Traefik (HTTPS) and one for WOL broadcast

### Ollama Proxy Implementation
Proxy endpoints implement full passthrough to Ollama:
- All endpoints verify host connectivity before proxying
- Support both streaming (`StreamingResponse`) and non-streaming responses
- Streaming uses `httpx.AsyncClient.stream()` with chunk iteration
- Generate/Chat: 300s timeout
- Pull: 3600s timeout (1 hour for large models)
- Delete/Show: 30s timeout
- Returns appropriate HTTP errors (503 if offline, 504 on timeout, 500 on other errors)

### Docker Networking Architecture
The project uses a dual-network configuration:
- **proxy network**: External network connecting to Traefik for HTTPS routing
- **macvlan_local network**: External macvlan network for direct layer-2 access to send WOL packets

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

### Docker and Traefik Configuration
The project uses Docker Compose with overlay files:
- Base: `docker-compose.yml` (defines service, references external `proxy` network)
- Traefik overlay: `docker-compose.traefik.yml` (adds macvlan network, Traefik labels, ports)

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

### Deployment Script
`desplegar_docker.sh` automates the full deployment workflow:
1. Updates repository via `git pull`
2. Verifies `proxy` network exists (creates if missing)
3. Verifies `macvlan_local` network exists (exits with instructions if missing)
4. Stops existing container
5. Builds and starts container with both docker-compose files
6. Displays status and helpful commands

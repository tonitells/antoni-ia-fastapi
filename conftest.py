"""
Pytest configuration and fixtures for antoni-ia-fastapi tests.
"""
import pytest
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def test_api_key():
    """API key válida para tests."""
    return "test_api_key_12345"


@pytest.fixture
def invalid_api_key():
    """API key inválida para tests."""
    return "invalid_key"


@pytest.fixture
def test_env_vars(test_api_key, tmp_path):
    """Configure environment variables for testing."""
    env_vars = {
        "EQUIPO_IA": "192.168.1.100",
        "IA_MAC": "00:11:22:33:44:55",
        "OLLAMA_PORT": "11434",
        "SSH_USER": "testuser",
        "SSH_PASS": "testpass",
        "SSH_SUDO_PASS": "testpass",
        "SSH_PORT": "22",
        "API_KEYS": f"{test_api_key},another_key",
        "WOL_BROADCAST": "192.168.1.255",
        "WOL_PORT": "9",
        "SUBDOMINIO": "test.example.com"
    }

    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def temp_status_dir(tmp_path, monkeypatch):
    """Create a temporary status directory for tests."""
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    # Create base.json
    base_status = {
        "logical_on": False,
        "phisical_on": False,
        "peticions_ollama": 0,
        "permanent_on": False,
        "message": "Equip offline",
        "datetime": "2024-10-05T12:34:56Z"
    }

    base_file = status_dir / "base.json"
    with open(base_file, 'w', encoding='utf-8') as f:
        json.dump(base_status, f, indent=4)

    # Patch the STATUS_FILE and BASE_STATUS_FILE paths
    from pathlib import Path
    monkeypatch.setattr("main.STATUS_FILE", status_dir / "status.json")
    monkeypatch.setattr("main.BASE_STATUS_FILE", status_dir / "base.json")

    return status_dir


@pytest.fixture
def client(test_env_vars, temp_status_dir):
    """
    Create a TestClient for the FastAPI app.
    Imports main after environment is set up.
    """
    # Import main AFTER environment variables are set
    import main

    # Reload the module to pick up new env vars
    import importlib
    importlib.reload(main)

    from main import app

    return TestClient(app)


@pytest.fixture
def mock_check_connectivity_online():
    """Mock check_host_connectivity to return True (equipment online)."""
    with patch("main.check_host_connectivity", new_callable=AsyncMock) as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_check_connectivity_offline():
    """Mock check_host_connectivity to return False (equipment offline)."""
    with patch("main.check_host_connectivity", new_callable=AsyncMock) as mock:
        mock.return_value = False
        yield mock


@pytest.fixture
def mock_ollama_online():
    """Mock httpx.AsyncClient to simulate Ollama responding correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": []}

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        yield mock_client


@pytest.fixture
def mock_ollama_offline():
    """Mock httpx.AsyncClient to simulate Ollama connection error."""
    import httpx

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        yield mock_client


@pytest.fixture
def mock_wol():
    """Mock wakeonlan send_magic_packet."""
    with patch("main.send_magic_packet") as mock:
        yield mock


@pytest.fixture
def mock_ssh_success():
    """Mock paramiko SSH client for successful shutdown."""
    with patch("main.paramiko.SSHClient") as mock_ssh_class:
        mock_ssh = MagicMock()
        mock_ssh_class.return_value = mock_ssh

        # Mock successful command execution
        mock_stdout = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stdout.read.return_value = b""

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        mock_ssh.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        yield mock_ssh


@pytest.fixture
def mock_ssh_failure():
    """Mock paramiko SSH client for failed shutdown."""
    with patch("main.paramiko.SSHClient") as mock_ssh_class:
        mock_ssh = MagicMock()
        mock_ssh_class.return_value = mock_ssh

        # Mock failed command execution
        mock_stdout = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stdout.read.return_value = b"Error output"

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b"Permission denied"

        mock_ssh.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        yield mock_ssh


@pytest.fixture(autouse=True)
def reset_status_file(temp_status_dir):
    """Automatically reset status.json before each test."""
    status_file = temp_status_dir / "status.json"
    if status_file.exists():
        status_file.unlink()
    yield
    # Cleanup after test
    if status_file.exists():
        status_file.unlink()

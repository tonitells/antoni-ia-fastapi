"""
Comprehensive tests for antoni-ia-fastapi.
Tests cover authentication, status management, equipment control, and state logic.
"""
import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


class TestAuthentication:
    """Tests for API key authentication."""

    def test_root_endpoint_no_auth_required(self, client):
        """Test that root endpoint doesn't require authentication."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["api"] == "Antoni IA API"
        assert data["status"] == "running"

    def test_endpoint_without_api_key(self, client):
        """Test that protected endpoints reject requests without API key."""
        response = client.get("/test")
        assert response.status_code == 401  # FastAPI returns 401 for missing auth

    def test_endpoint_with_invalid_api_key(self, client, invalid_api_key):
        """Test that protected endpoints reject invalid API keys."""
        response = client.get("/test", headers={"X-API-Key": invalid_api_key})
        assert response.status_code == 401

    def test_endpoint_with_valid_api_key(self, client, test_api_key, mock_check_connectivity_offline):
        """Test that protected endpoints accept valid API keys."""
        response = client.get("/test", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200


class TestStatusManagement:
    """Tests for status file management functions."""

    def test_read_status_creates_from_base(self, client, test_api_key):
        """Test that read_status creates status.json from base.json if it doesn't exist."""
        # Simply call an endpoint that will trigger read_status
        response = client.get("/status", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert "logical_on" in data
        assert "phisical_on" in data
        assert "peticions_ollama" in data
        assert "permanent_on" in data

    def test_write_status_updates_datetime(self, client, test_api_key):
        """Test that write_status automatically updates datetime."""
        from datetime import datetime

        # Make a call that updates status
        response = client.post("/init", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert "datetime" in data["status"]
        # Verify it's a valid ISO format datetime
        datetime.fromisoformat(data["status"]["datetime"].replace('Z', '+00:00'))

    def test_update_status(self, client, test_api_key):
        """Test that update_status correctly updates fields."""
        # Enable permanent_on
        response = client.post("/permanent_on_enable", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        # Verify it was updated
        response = client.get("/status", headers={"X-API-Key": test_api_key})
        data = response.json()
        assert data["permanent_on"] is True


class TestStatusEndpoint:
    """Tests for GET /status endpoint."""

    def test_get_status(self, client, test_api_key, temp_status_dir, mock_check_connectivity_offline):
        """Test retrieving current status."""
        from main import update_status

        # Set some status
        asyncio.run(update_status(
            updates={"peticions_ollama": 2, "permanent_on": True},
            message="Test status"
        ))

        response = client.get("/status", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["peticions_ollama"] == 2
        assert data["permanent_on"] is True


class TestInitEndpoint:
    """Tests for POST /init endpoint."""

    def test_init_with_equipment_online_ollama_online(
        self, client, test_api_key, mock_check_connectivity_online, mock_ollama_online
    ):
        """Test init when equipment and Ollama are online."""
        response = client.post("/init", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["status"]["phisical_on"] is True
        assert data["status"]["logical_on"] is True
        assert data["status"]["peticions_ollama"] == 0
        assert data["status"]["permanent_on"] is False

    def test_init_with_equipment_offline(
        self, client, test_api_key, mock_check_connectivity_offline
    ):
        """Test init when equipment is offline."""
        response = client.post("/init", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["status"]["phisical_on"] is False
        assert data["status"]["logical_on"] is False
        assert data["status"]["peticions_ollama"] == 0
        assert data["status"]["permanent_on"] is False

    def test_init_resets_counters(self, client, test_api_key, mock_check_connectivity_offline):
        """Test that init resets counters even if they were non-zero."""
        from main import update_status

        # Set non-zero values
        asyncio.run(update_status(
            updates={"peticions_ollama": 5, "permanent_on": True},
            message="Before init"
        ))

        response = client.post("/init", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["status"]["peticions_ollama"] == 0
        assert data["status"]["permanent_on"] is False


class TestTestEndpoint:
    """Tests for GET /test endpoint."""

    def test_test_endpoint_updates_status(
        self, client, test_api_key, mock_check_connectivity_online, mock_ollama_online
    ):
        """Test that /test endpoint updates status correctly."""
        from main import read_status

        response = client.get("/test", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["equipo_online"] is True
        assert data["ollama_online"] is True

        # Check that status was updated (read_status is async now)
        status = asyncio.run(read_status())
        assert status["phisical_on"] is True
        assert status["logical_on"] is True

    def test_test_endpoint_equipment_offline(
        self, client, test_api_key, mock_check_connectivity_offline
    ):
        """Test /test when equipment is offline."""
        response = client.get("/test", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["equipo_online"] is False
        assert data["ollama_online"] is False


class TestArrancarEndpoint:
    """Tests for POST /arrancar endpoint."""

    def test_arrancar_increments_counter(
        self, client, test_api_key, mock_check_connectivity_offline, mock_wol
    ):
        """Test that /arrancar increments peticions_ollama counter."""
        from main import read_status

        response = client.post("/arrancar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "Peticions Ollama: 1" in data["mensaje"]

        # Verify WOL was called
        mock_wol.assert_called_once()

        # Check status
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 1

    def test_arrancar_multiple_times(
        self, client, test_api_key, mock_check_connectivity_offline, mock_wol
    ):
        """Test multiple arrancar calls increment counter correctly."""
        # Initialize first to reset counter
        client.post("/init", headers={"X-API-Key": test_api_key})

        # First call
        response = client.post("/arrancar", headers={"X-API-Key": test_api_key})
        assert "Peticions Ollama: 1" in response.json()["mensaje"]

        # Second call
        response = client.post("/arrancar", headers={"X-API-Key": test_api_key})
        assert "Peticions Ollama: 2" in response.json()["mensaje"]

        # Third call
        response = client.post("/arrancar", headers={"X-API-Key": test_api_key})
        assert "Peticions Ollama: 3" in response.json()["mensaje"]

        # Verify final status
        response = client.get("/status", headers={"X-API-Key": test_api_key})
        assert response.json()["peticions_ollama"] == 3

    def test_arrancar_when_already_online(
        self, client, test_api_key, mock_check_connectivity_online, mock_wol
    ):
        """Test arrancar when equipment is already online."""
        response = client.post("/arrancar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "ja està encès" in data["mensaje"]

        # WOL should NOT be called when already online
        mock_wol.assert_not_called()


class TestApagarEndpoint:
    """Tests for POST /apagar endpoint."""

    def test_apagar_decrements_counter(
        self, client, test_api_key, mock_check_connectivity_online, mock_ssh_success
    ):
        """Test that /apagar decrements counter."""
        from main import update_status, read_status

        # Set counter to 2
        asyncio.run(update_status(updates={"peticions_ollama": 2}, message="Setup"))

        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 1

    def test_apagar_does_not_shutdown_with_active_requests(
        self, client, test_api_key, mock_check_connectivity_online, mock_ssh_success
    ):
        """Test that apagar does NOT shutdown physically when peticions > 0."""
        from main import update_status

        # Set counter to 2
        asyncio.run(update_status(updates={"peticions_ollama": 2}, message="Setup"))

        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert "No s'apaga físicament" in data["mensaje"]
        assert "petició(ns) activa(es)" in data["mensaje"]

        # SSH should NOT be called
        mock_ssh_success.connect.assert_not_called()

    def test_apagar_shutdowns_when_counter_reaches_zero(
        self, client, test_api_key, mock_check_connectivity_online, mock_ssh_success
    ):
        """Test that apagar DOES shutdown physically when peticions reaches 0."""
        from main import update_status, read_status

        # Set counter to 1
        asyncio.run(update_status(updates={"peticions_ollama": 1}, message="Setup"))

        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "Apagat físic enviat" in data["mensaje"]

        # SSH should be called
        mock_ssh_success.connect.assert_called()

        # After shutdown, mock connectivity to be offline
        mock_check_connectivity_online.return_value = False

        # Check status
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0
        assert status["phisical_on"] is False
        assert status["logical_on"] is False

    def test_apagar_respects_permanent_on(
        self, client, test_api_key, mock_check_connectivity_online, mock_ssh_success
    ):
        """Test that apagar does NOT shutdown when permanent_on is True."""
        from main import update_status, read_status

        # Set counter to 1 and permanent_on to True
        asyncio.run(update_status(
            updates={"peticions_ollama": 1, "permanent_on": True},
            message="Setup"
        ))

        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert "No s'apaga físicament" in data["mensaje"]
        assert "permanent_on activat" in data["mensaje"]

        # SSH should NOT be called
        mock_ssh_success.connect.assert_not_called()

        # Counter still decrements
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0

    def test_apagar_when_already_offline(
        self, client, test_api_key, mock_check_connectivity_offline
    ):
        """Test apagar when equipment is already offline."""
        from main import update_status, read_status

        asyncio.run(update_status(updates={"peticions_ollama": 2}, message="Setup"))

        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert "ja està apagat" in data["mensaje"]

        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 1

    def test_apagar_counter_minimum_zero(
        self, client, test_api_key, mock_check_connectivity_offline
    ):
        """Test that counter doesn't go below zero."""
        from main import read_status

        # Start with 0
        client.post("/init", headers={"X-API-Key": test_api_key})

        # Try to decrement
        client.post("/apagar", headers={"X-API-Key": test_api_key})

        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0  # Should not be negative


class TestPermanentOnEndpoints:
    """Tests for permanent_on enable/disable endpoints."""

    def test_permanent_on_enable(self, client, test_api_key, mock_check_connectivity_offline):
        """Test enabling permanent_on mode."""
        from main import read_status

        response = client.post("/permanent_on_enable", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

        status = asyncio.run(read_status())
        assert status["permanent_on"] is True

    def test_permanent_on_disable(self, client, test_api_key, mock_check_connectivity_offline):
        """Test disabling permanent_on mode."""
        from main import update_status, read_status

        # First enable it
        asyncio.run(update_status(updates={"permanent_on": True}, message="Setup"))

        response = client.post("/permanent_on_disable", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

        status = asyncio.run(read_status())
        assert status["permanent_on"] is False


class TestShutdownEndpoint:
    """Tests for POST /shutdown endpoint (forced shutdown)."""

    def test_shutdown_resets_all_state(
        self, client, test_api_key, mock_check_connectivity_online, mock_ssh_success
    ):
        """Test that shutdown resets all state variables."""
        from main import update_status, read_status

        # Set some non-default values
        asyncio.run(update_status(
            updates={
                "peticions_ollama": 5,
                "permanent_on": True,
                "logical_on": True,
                "phisical_on": True
            },
            message="Setup"
        ))

        response = client.post("/shutdown", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "resetejat" in data["mensaje"]

        # After shutdown, mock connectivity to be offline
        mock_check_connectivity_online.return_value = False

        # Verify all state is reset
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0
        assert status["permanent_on"] is False
        assert status["logical_on"] is False
        assert status["phisical_on"] is False

    def test_shutdown_calls_ssh(
        self, client, test_api_key, mock_check_connectivity_online, mock_ssh_success
    ):
        """Test that shutdown calls SSH to power off equipment."""
        response = client.post("/shutdown", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        # Verify SSH was called
        mock_ssh_success.connect.assert_called()
        mock_ssh_success.exec_command.assert_called()

    def test_shutdown_when_already_offline(
        self, client, test_api_key, mock_check_connectivity_offline
    ):
        """Test shutdown when equipment is already offline."""
        from main import read_status

        response = client.post("/shutdown", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        data = response.json()
        assert "ja està apagat" in data["mensaje"]

        # State should still be reset
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0
        assert status["permanent_on"] is False


class TestComplexScenarios:
    """Tests for complex multi-step scenarios."""

    def test_full_lifecycle(
        self,
        client,
        test_api_key,
        mock_check_connectivity_offline,
        mock_check_connectivity_online,
        mock_wol,
        mock_ssh_success
    ):
        """Test a complete lifecycle: init -> arrancar -> arrancar -> apagar -> apagar."""
        from main import read_status

        # 1. Initialize
        client.post("/init", headers={"X-API-Key": test_api_key})
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0

        # 2. First arrancar (equipment offline)
        mock_check_connectivity_offline.return_value = False
        response = client.post("/arrancar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 1

        # 3. Second arrancar (equipment now online)
        mock_check_connectivity_online.return_value = True
        response = client.post("/arrancar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 2

        # 4. First apagar (should NOT shutdown, counter > 0)
        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200
        assert "No s'apaga físicament" in response.json()["mensaje"]
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 1
        mock_ssh_success.connect.assert_not_called()

        # 5. Second apagar (should shutdown, counter reaches 0)
        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200
        assert "Apagat físic enviat" in response.json()["mensaje"]
        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0
        mock_ssh_success.connect.assert_called()

    def test_permanent_on_blocks_shutdown(
        self,
        client,
        test_api_key,
        mock_check_connectivity_online,
        mock_ssh_success
    ):
        """Test that permanent_on prevents automatic shutdown."""
        from main import read_status

        # Initialize and arrancar
        client.post("/init", headers={"X-API-Key": test_api_key})
        client.post("/arrancar", headers={"X-API-Key": test_api_key})

        # Enable permanent_on
        client.post("/permanent_on_enable", headers={"X-API-Key": test_api_key})

        # Try to apagar (should NOT shutdown)
        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert "permanent_on activat" in response.json()["mensaje"]
        mock_ssh_success.connect.assert_not_called()

        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0  # Counter decremented
        assert status["permanent_on"] is True

        # Disable permanent_on
        client.post("/permanent_on_disable", headers={"X-API-Key": test_api_key})

        # Now arrancar and apagar should work normally
        client.post("/arrancar", headers={"X-API-Key": test_api_key})
        response = client.post("/apagar", headers={"X-API-Key": test_api_key})
        assert "Apagat físic enviat" in response.json()["mensaje"]
        mock_ssh_success.connect.assert_called()

    def test_shutdown_overrides_everything(
        self,
        client,
        test_api_key,
        mock_check_connectivity_online,
        mock_ssh_success
    ):
        """Test that /shutdown overrides permanent_on and counters."""
        from main import update_status, read_status

        # Set up state with permanent_on and high counter
        asyncio.run(update_status(
            updates={
                "peticions_ollama": 10,
                "permanent_on": True
            },
            message="Setup"
        ))

        # Shutdown should ignore everything
        response = client.post("/shutdown", headers={"X-API-Key": test_api_key})
        assert response.status_code == 200

        status = asyncio.run(read_status())
        assert status["peticions_ollama"] == 0
        assert status["permanent_on"] is False
        mock_ssh_success.connect.assert_called()

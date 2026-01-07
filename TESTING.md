# Testing Guide for Antoni IA API

This document describes the test suite for the Antoni IA FastAPI application.

## Test Structure

The test suite consists of:
- **conftest.py**: Pytest fixtures and configuration
- **test_main.py**: Main test file with 30 comprehensive tests
- **pytest.ini**: Pytest configuration

## Running Tests

### Install Test Dependencies

```bash
pip install -r requirements-dev.txt
```

### Run All Tests

```bash
# Run all tests with verbose output
pytest test_main.py -v

# Run all tests with coverage (if pytest-cov installed)
pytest test_main.py --cov=main --cov-report=html

# Run tests in specific class
pytest test_main.py::TestAuthentication -v

# Run specific test
pytest test_main.py::TestArrancarEndpoint::test_arrancar_increments_counter -v
```

### Run Tests with Different Verbosity

```bash
# Minimal output
pytest test_main.py -q

# Verbose output
pytest test_main.py -v

# Very verbose (show individual test output)
pytest test_main.py -vv
```

## Test Coverage

The test suite covers:

### 1. Authentication (4 tests)
- Root endpoint accessibility without auth
- Protected endpoints reject requests without API key
- Protected endpoints reject invalid API keys
- Protected endpoints accept valid API keys

### 2. Status Management (3 tests)
- Reading status from file
- Writing status with automatic datetime updates
- Updating specific status fields

### 3. Status Endpoint (1 test)
- GET /status returns current state

### 4. Init Endpoint (3 tests)
- Initialization with equipment online and Ollama online
- Initialization with equipment offline
- Initialization resets counters to zero

### 5. Test Endpoint (2 tests)
- GET /test updates status correctly
- GET /test handles offline equipment

### 6. Arrancar Endpoint (3 tests)
- POST /arrancar increments peticions_ollama counter
- Multiple arrancar calls increment correctly
- Arrancar when equipment is already online

### 7. Apagar Endpoint (6 tests)
- POST /apagar decrements counter
- Apagar does NOT shutdown with active requests (counter > 0)
- Apagar DOES shutdown when counter reaches 0
- Apagar respects permanent_on flag
- Apagar when equipment is already offline
- Counter never goes below zero

### 8. Permanent On Endpoints (2 tests)
- POST /permanent_on_enable activates mode
- POST /permanent_on_disable deactivates mode

### 9. Shutdown Endpoint (3 tests)
- POST /shutdown resets all state variables
- Shutdown calls SSH to power off equipment
- Shutdown when equipment is already offline

### 10. Complex Scenarios (3 tests)
- Full lifecycle: init -> arrancar -> arrancar -> apagar -> apagar
- Permanent_on blocks automatic shutdown
- Shutdown overrides permanent_on and counters

## Test Fixtures

### Environment Fixtures
- `test_api_key`: Valid API key for testing
- `invalid_api_key`: Invalid API key for negative tests
- `test_env_vars`: Mocked environment variables
- `temp_status_dir`: Temporary directory for status files

### Mock Fixtures
- `client`: TestClient for FastAPI app
- `mock_check_connectivity_online`: Mock equipment as online
- `mock_check_connectivity_offline`: Mock equipment as offline
- `mock_ollama_online`: Mock Ollama responding correctly
- `mock_ollama_offline`: Mock Ollama connection error
- `mock_wol`: Mock Wake-on-LAN function
- `mock_ssh_success`: Mock successful SSH shutdown
- `mock_ssh_failure`: Mock failed SSH shutdown

## Writing New Tests

### Example Test Structure

```python
def test_new_feature(self, client, test_api_key, mock_check_connectivity_online):
    """Test description."""
    # Setup
    # ... prepare test data

    # Execute
    response = client.post("/endpoint", headers={"X-API-Key": test_api_key})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["expected_field"] == expected_value
```

### Best Practices

1. **Use descriptive test names**: Start with `test_` and describe what is being tested
2. **One assertion per concept**: Test one thing at a time
3. **Use fixtures**: Leverage existing fixtures to avoid code duplication
4. **Mock external dependencies**: Always mock SSH, WOL, and network calls
5. **Clean state**: Each test should be independent and not rely on other tests

## Test Results

Current test results: **30/30 tests passing (100%)**

```
============================= 30 passed in 13.82s =============================
```

## CI/CD Integration

To integrate tests in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pip install -r requirements-dev.txt
    pytest test_main.py -v --junitxml=test-results.xml

- name: Publish test results
  uses: actions/upload-artifact@v2
  with:
    name: test-results
    path: test-results.xml
```

## Troubleshooting

### Import Errors
If you get import errors, ensure you're running tests from the project root:
```bash
cd /path/to/antoni-ia-fastapi
pytest test_main.py
```

### Fixture Not Found
Make sure `conftest.py` is in the same directory as your tests.

### Mock Not Working
Check that mocks are properly scoped and applied before the client fixture is created.

## Future Improvements

Potential areas for additional testing:
- Integration tests with real Ollama instance (optional)
- Performance/load testing for concurrent requests
- Security testing for API key handling
- Edge cases for network timeouts
- Testing with actual status.json file operations

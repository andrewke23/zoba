import os

# Importing app.core.security builds the database engine from Settings, which
# requires a JWT secret; provide one so unit tests can import app modules.
os.environ.setdefault("JWT_SECRET_KEY", "unit-test-secret-that-is-long-enough-0123456789")

# Ensures the backend/ directory is importable as the project root for tests,
# so `import app.*` works whether tests run via `pytest` or `python -m pytest`.

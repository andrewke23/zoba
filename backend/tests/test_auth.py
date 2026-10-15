from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt
import pytest
from pydantic import ValidationError

from app.api.auth import _hash_password, _verify_password
from app.core.security import create_access_token
from app.schemas.auth import UserLogin, UserRegister

USER_ID = UUID("00000000-0000-0000-0000-000000000009")


def test_password_hash_round_trip_and_wrong_password() -> None:
    password = "correct horse battery staple"
    stored = _hash_password(password)

    assert stored != password
    assert stored.startswith("$2")
    assert _verify_password(password, stored)
    assert not _verify_password("wrong password", stored)


def test_verify_password_rejects_non_bcrypt_stored_values() -> None:
    assert not _verify_password("anything", "not-a-bcrypt-hash")


def test_access_token_round_trips_with_required_claims() -> None:
    token = create_access_token(USER_ID)

    claims = jwt.decode(
        token,
        "unit-test-secret-that-is-long-enough-0123456789",
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
    assert UUID(claims["sub"]) == USER_ID
    assert claims["exp"] > datetime.now(timezone.utc).timestamp() + timedelta(minutes=5).total_seconds()


def test_register_normalizes_email_and_enforces_password_rules() -> None:
    payload = UserRegister.model_validate(
        {"email": "  Alice@Example.COM ", "name": "Alice", "password": "long enough password"}
    )
    assert payload.email == "alice@example.com"

    with pytest.raises(ValidationError, match="at least 8"):
        UserRegister.model_validate(
            {"email": "alice@example.com", "name": "Alice", "password": "short"}
        )

    with pytest.raises(ValidationError, match="72 bytes"):
        UserRegister.model_validate(
            {"email": "alice@example.com", "name": "Alice", "password": "x" * 73}
        )

    with pytest.raises(ValidationError):
        UserRegister.model_validate({"email": "not-an-email", "name": "Alice", "password": "long enough password"})


def test_login_requires_a_password() -> None:
    with pytest.raises(ValidationError):
        UserLogin.model_validate({"email": "alice@example.com", "password": ""})


def test_bcrypt_hash_stored_shape_matches_database_column() -> None:
    stored = _hash_password("correct horse battery staple")

    # bcrypt.checkpw must accept what _hash_password produces, and the value
    # must fit app_user.password_hash (TEXT) unchanged.
    assert bcrypt.checkpw(b"correct horse battery staple", stored.encode("utf-8"))

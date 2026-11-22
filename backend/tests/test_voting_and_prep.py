from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.preferences import _validate_preferences
from app.main import app
from app.schemas.preferences import ComparisonCreate, PreferenceItem
from app.schemas.prep import PackingItemCreate, PackingItemUpdate, TaskCreate, TaskUpdate

A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
B = UUID("bbbbbbbb-0000-0000-0000-000000000002")
OUTSIDE = UUID("eeeeeeee-0000-0000-0000-000000000005")
CATALOG = {A: ("Museum", "museum"), B: ("Park", "park")}


def test_every_frontend_endpoint_is_routed() -> None:
    routes = {(method.upper(), path) for path, ops in app.openapi()["paths"].items() for method in ops}
    base = "/api/v1/trips/{trip_id}"
    expected = {
        ("GET", f"{base}/preference-config"),
        ("GET", f"{base}/preferences/me"),
        ("PUT", f"{base}/preferences/me"),
        ("GET", f"{base}/comparisons/progress"),
        ("POST", f"{base}/comparisons"),
        ("GET", f"{base}/group-results"),
        ("GET", f"{base}/tasks"),
        ("POST", f"{base}/tasks"),
        ("PATCH", f"{base}/tasks/{{task_id}}"),
        ("DELETE", f"{base}/tasks/{{task_id}}"),
        ("GET", f"{base}/packing"),
        ("POST", f"{base}/packing"),
        ("PUT", f"{base}/packing/{{item_id}}"),
        ("DELETE", f"{base}/packing/{{item_id}}"),
    }
    assert expected <= routes


def test_preferences_within_budget_pass() -> None:
    _validate_preferences([PreferenceItem(destination_id=A, points=60), PreferenceItem(destination_id=B, points=40)], CATALOG)


def test_vetoed_points_do_not_count_toward_the_budget() -> None:
    _validate_preferences(
        [PreferenceItem(destination_id=A, points=100), PreferenceItem(destination_id=B, points=50, hard_no=True)],
        CATALOG,
    )


@pytest.mark.parametrize(
    "items, message",
    [
        ([PreferenceItem(destination_id=A, points=60), PreferenceItem(destination_id=B, points=41)], "at most 100"),
        ([PreferenceItem(destination_id=A, points=1), PreferenceItem(destination_id=A, points=1)], "only once"),
        ([PreferenceItem(destination_id=OUTSIDE, points=1)], "trip's city"),
    ],
)
def test_invalid_preferences_are_rejected(items, message) -> None:
    with pytest.raises(HTTPException) as caught:
        _validate_preferences(items, CATALOG)
    assert caught.value.status_code == 400
    assert message in caught.value.detail


def test_negative_points_and_zero_rank_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PreferenceItem(destination_id=A, points=-1)
    with pytest.raises(ValidationError):
        PreferenceItem(destination_id=A, points=0, rank=0)


def test_comparison_choice_must_be_in_the_pair() -> None:
    assert ComparisonCreate(dest_a=A, dest_b=B, chosen=B).chosen == B
    with pytest.raises(ValidationError):
        ComparisonCreate(dest_a=A, dest_b=B, chosen=OUTSIDE)
    with pytest.raises(ValidationError):
        ComparisonCreate(dest_a=A, dest_b=A, chosen=A)


def test_task_and_packing_labels_are_trimmed_and_required() -> None:
    assert TaskCreate(title="  Book tickets ").title == "Book tickets"
    assert PackingItemCreate(label=" Sunscreen ").label == "Sunscreen"
    for blank in ("", "   "):
        with pytest.raises(ValidationError):
            TaskCreate(title=blank)
        with pytest.raises(ValidationError):
            PackingItemUpdate(label=blank, packed=True)


def test_task_status_is_open_or_done() -> None:
    assert TaskUpdate(status="done").status == "done"
    with pytest.raises(ValidationError):
        TaskUpdate(status="archived")

import pytest

from app.tasks import execute_task


def test_record_order_created_task():
    result = execute_task(
        "record_order_created",
        {"order_id": "1001"},
    )

    assert result["task"] == "record_order_created"
    assert result["order_id"] == "1001"
    assert "recorded_at" in result


def test_record_inventory_update_task():
    result = execute_task(
        "record_inventory_update",
        {"product_id": "SKU-1", "quantity": 5},
    )

    assert result["task"] == "record_inventory_update"
    assert result["product_id"] == "SKU-1"
    assert result["quantity"] == 5


def test_unknown_task_is_rejected():
    with pytest.raises(ValueError, match="Unknown task handler"):
        execute_task("not_a_real_task", {})

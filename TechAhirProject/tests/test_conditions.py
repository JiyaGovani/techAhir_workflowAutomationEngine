from app.routes import validate_steps
from app.worker import evaluate_condition


def test_greater_than_condition():
    step = {"field": "order_value", "operator": "gt", "value": 500}
    assert evaluate_condition({"order_value": 600}, step) is True
    assert evaluate_condition({"order_value": 400}, step) is False


def test_missing_field_is_false():
    step = {"field": "order_value", "operator": "gt", "value": 500}
    assert evaluate_condition({}, step) is False


def test_condition_workflow_validation():
    steps = [
        {
            "type": "CONDITION",
            "field": "order_value",
            "operator": "gt",
            "value": 500,
            "true_next": 1,
            "false_next": None,
        },
        {
            "type": "MESSAGE",
            "recipient": "customer@example.com",
            "content": "Follow up",
        },
    ]

    assert validate_steps(steps) is None


def test_condition_rejects_invalid_target():
    steps = [{
        "type": "CONDITION",
        "field": "order_value",
        "operator": "gt",
        "value": 500,
        "true_next": 99,
        "false_next": None,
    }]

    assert "outside the workflow" in validate_steps(steps)

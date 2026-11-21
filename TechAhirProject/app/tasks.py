from datetime import datetime, timezone


def record_order_created(config):
    return {
        "task": "record_order_created",
        "order_id": config.get("order_id", "unknown"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def record_inventory_update(config):
    return {
        "task": "record_inventory_update",
        "product_id": config.get("product_id", "unknown"),
        "quantity": config.get("quantity", 0),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


TASK_HANDLERS = {
    "record_order_created": record_order_created,
    "record_inventory_update": record_inventory_update,
}


def execute_task(task_name, config):
    handler = TASK_HANDLERS.get(task_name)
    if handler is None:
        raise ValueError("Unknown task handler: " + str(task_name))
    return handler(config)

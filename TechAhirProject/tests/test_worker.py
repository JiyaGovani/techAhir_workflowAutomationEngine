import json
import os
import sqlite3
import tempfile

from app import create_app
from app.worker import claim_execution, process_execution


def create_database():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": path,
    })
    app_context = app.app_context()
    app_context.push()

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return app, app_context, connection, path


def insert_workflow(connection, steps, input_data=None):
    cursor = connection.execute(
        "INSERT INTO workflows (name, definition) VALUES (?, ?)",
        ("Integration workflow", json.dumps({"steps": steps})),
    )
    workflow_id = cursor.lastrowid
    cursor = connection.execute(
        """
        INSERT INTO workflow_executions
            (workflow_id, status, input_data)
        VALUES (?, 'PENDING', ?)
        """,
        (workflow_id, json.dumps(input_data or {})),
    )
    execution_id = cursor.lastrowid
    connection.commit()
    return workflow_id, execution_id


def test_task_and_message_execution():
    app, app_context, connection, path = create_database()
    try:
        _, execution_id = insert_workflow(
            connection,
            [
                {
                    "type": "TASK",
                    "task": "record_order_created",
                    "config": {"order_id": "I-100"},
                },
                {
                    "type": "MESSAGE",
                    "recipient": "customer@example.com",
                    "content": "Integration message",
                },
            ],
        )

        claimed = claim_execution(path)
        assert claimed["id"] == execution_id
        for _ in range(4):
            process_execution(path, execution_id)

        execution = connection.execute(
            "SELECT * FROM workflow_executions WHERE id = ?",
            (execution_id,),
        ).fetchone()
        messages = connection.execute(
            "SELECT * FROM messages WHERE execution_id = ?",
            (execution_id,),
        ).fetchall()
        steps = connection.execute(
            """
            SELECT * FROM execution_steps
            WHERE execution_id = ?
            ORDER BY step_index
            """,
            (execution_id,),
        ).fetchall()

        assert execution["status"] == "COMPLETED"
        assert len(messages) == 1
        assert [row["status"] for row in steps] == ["COMPLETED", "COMPLETED"]

        process_execution(path, execution_id)
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()
        app_context.pop()
        os.unlink(path)


def test_wait_resumes_without_repeating_completed_task():
    app, app_context, connection, path = create_database()
    try:
        _, execution_id = insert_workflow(
            connection,
            [
                {
                    "type": "TASK",
                    "task": "record_order_created",
                    "config": {"order_id": "WAIT-100"},
                },
                {"type": "WAIT", "seconds": 0},
                {
                    "type": "MESSAGE",
                    "recipient": "customer@example.com",
                    "content": "Resumed message",
                },
            ],
        )

        for _ in range(6):
            process_execution(path, execution_id)

        execution = connection.execute(
            "SELECT * FROM workflow_executions WHERE id = ?",
            (execution_id,),
        ).fetchone()
        task_steps = connection.execute(
            """
            SELECT COUNT(*) FROM execution_steps
            WHERE execution_id = ? AND step_type = 'TASK'
            """,
            (execution_id,),
        ).fetchone()[0]

        assert execution["status"] == "COMPLETED"
        assert task_steps == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()
        app_context.pop()
        os.unlink(path)


def test_condition_branch_skips_false_path():
    app, app_context, connection, path = create_database()
    try:
        _, execution_id = insert_workflow(
            connection,
            [
                {
                    "type": "CONDITION",
                    "field": "order_value",
                    "operator": "gt",
                    "value": 500,
                    "true_next": 2,
                    "false_next": None,
                },
                {
                    "type": "MESSAGE",
                    "recipient": "customer@example.com",
                    "content": "This step is skipped",
                },
                {
                    "type": "MESSAGE",
                    "recipient": "customer@example.com",
                    "content": "This step is sent",
                },
            ],
            {"order_value": 600},
        )

        for _ in range(4):
            process_execution(path, execution_id)

        execution = connection.execute(
            "SELECT * FROM workflow_executions WHERE id = ?",
            (execution_id,),
        ).fetchone()
        messages = connection.execute(
            "SELECT content FROM messages WHERE execution_id = ?",
            (execution_id,),
        ).fetchall()

        assert execution["status"] == "COMPLETED"
        assert [row["content"] for row in messages] == ["This step is sent"]
    finally:
        connection.close()
        app_context.pop()
        os.unlink(path)

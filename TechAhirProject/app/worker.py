import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from app.tasks import execute_task


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evaluate_condition(input_data, step):
    field = step.get("field")
    operator = step.get("operator")
    expected = step.get("value")
    actual = input_data.get(field)

    try:
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "eq":
            return actual == expected
        if operator == "ne":
            return actual != expected
        if operator == "in":
            return actual in expected
        raise ValueError("Unsupported condition operator: " + str(operator))
    except (KeyError, TypeError):
        return False


def connect(database_path):
    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def claim_execution(database_path):
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        now = utc_now()
        row = connection.execute(
            """
            SELECT id
            FROM workflow_executions
            WHERE status = 'PENDING'
               OR status = 'RUNNING'
            ORDER BY updated_at
            LIMIT 1
            """,
        ).fetchone()
        if row is None:
            connection.commit()
            return None

        connection.execute(
            """
            UPDATE workflow_executions
            SET status = 'RUNNING',
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, row["id"]),
        )
        connection.commit()
        return {"id": row["id"]}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def process_execution(database_path, execution_id):
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        execution = connection.execute(
            """
            SELECT we.id, we.current_step_index, we.input_data, w.definition
            FROM workflow_executions we
            JOIN workflows w ON w.id = we.workflow_id
            WHERE we.id = ?
            """,
            (execution_id,),
        ).fetchone()
        if execution is None:
            connection.commit()
            return

        steps = json.loads(execution["definition"])
        steps = steps.get("steps", [])
        step_index = execution["current_step_index"]

        if step_index >= len(steps):
            connection.execute(
                """
                UPDATE workflow_executions
                SET status = 'COMPLETED', completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), utc_now(), execution_id),
            )
            connection.commit()
            return

        step = steps[step_index]
        step_type = step.get("type")
        step_row = connection.execute(
            """
            SELECT * FROM execution_steps
            WHERE execution_id = ? AND step_index = ?
            """,
            (execution_id, step_index),
        ).fetchone()

        if step_row is None:
            cursor = connection.execute(
                """
                INSERT INTO execution_steps
                    (execution_id, step_index, step_type, step_config)
                VALUES (?, ?, ?, ?)
                """,
                (execution_id, step_index, step_type, json.dumps(step)),
            )
            step_row = connection.execute(
                "SELECT * FROM execution_steps WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()

        if step_row["status"] == "COMPLETED":
            advance_execution(connection, execution_id, step_index, step_row)
            connection.commit()
            return

        if step_row["status"] == "FAILED":
            connection.execute(
                """
                UPDATE workflow_executions
                SET status = 'FAILED', error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (step_row["error_message"], utc_now(), execution_id),
            )
            connection.commit()
            return

        if step_row["status"] == "WAITING":
            now = utc_now()
            if step_row["resume_at"] and step_row["resume_at"] <= now:
                connection.execute(
                    """
                    UPDATE execution_steps
                    SET status = 'COMPLETED', completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, step_row["id"]),
                )
                advance_execution(connection, execution_id, step_index)
            connection.commit()
            return

        if step_row["status"] == "PENDING" and step_row["retry_at"]:
            if step_row["retry_at"] > utc_now():
                connection.commit()
                return

        connection.execute(
            """
            UPDATE execution_steps
            SET status = 'RUNNING',
                attempt_count = attempt_count + 1,
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), utc_now(), step_row["id"]),
        )

        try:
            if step_type == "TASK":
                result = execute_task(step.get("task"), step.get("config", {}))
                complete_step(connection, step_row["id"], result=result)
                advance_execution(connection, execution_id, step_index)

            elif step_type == "WAIT":
                duration_seconds = int(step.get("seconds", 0))
                resume_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
                ).isoformat(timespec="seconds")
                connection.execute(
                    """
                    UPDATE execution_steps
                    SET status = 'WAITING', resume_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (resume_at, utc_now(), step_row["id"]),
                )

            elif step_type == "MESSAGE":
                connection.execute(
                    """
                    INSERT OR IGNORE INTO messages
                        (execution_id, step_id, recipient, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        execution_id,
                        step_row["id"],
                        str(step.get("recipient", "")),
                        str(step.get("content", "")),
                    ),
                )
                complete_step(connection, step_row["id"])
                advance_execution(connection, execution_id, step_index)

            elif step_type == "CONDITION":
                input_data = json.loads(execution["input_data"] or "{}")
                condition_result = evaluate_condition(input_data, step)
                target_index = (
                    step.get("true_next")
                    if condition_result
                    else step.get("false_next")
                )
                complete_step(
                    connection,
                    step_row["id"],
                    result={
                        "condition": condition_result,
                        "target_index": target_index,
                    },
                )
                advance_execution(
                    connection,
                    execution_id,
                    step_index,
                    target_index=target_index,
                )
            else:
                raise ValueError("Unsupported step type: " + str(step_type))
        except Exception as error:
            handle_step_failure(
                connection,
                execution_id,
                step_row,
                str(error),
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_step(connection, step_id, result=None):
    connection.execute(
        """
        UPDATE execution_steps
        SET status = 'COMPLETED',
            result = ?,
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(result) if result is not None else None,
            utc_now(),
            utc_now(),
            step_id,
        ),
    )


ADVANCE_NEXT = object()


def advance_execution(connection, execution_id, step_index, step_row=None, target_index=ADVANCE_NEXT):
    if step_row is not None and step_row["step_type"] == "CONDITION":
        result = json.loads(step_row["result"]) if step_row["result"] else {}
        target_index = result.get("target_index")

    if target_index is None:
        connection.execute(
            """
            UPDATE workflow_executions
            SET status = 'COMPLETED', completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), utc_now(), execution_id),
        )
    else:
        next_index = step_index + 1 if target_index is ADVANCE_NEXT else target_index
        connection.execute(
            """
            UPDATE workflow_executions
            SET current_step_index = ?, status = 'RUNNING', updated_at = ?
            WHERE id = ?
            """,
            (next_index, utc_now(), execution_id),
        )


def handle_step_failure(connection, execution_id, step_row, error_message):
    attempt_count = step_row["attempt_count"] + 1
    if attempt_count < step_row["max_attempts"]:
        delay = 2 ** (attempt_count - 1)
        retry_at = (
            datetime.now(timezone.utc) + timedelta(seconds=delay)
        ).isoformat(timespec="seconds")
        connection.execute(
            """
            UPDATE execution_steps
            SET status = 'PENDING', error_message = ?, retry_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (error_message, retry_at, utc_now(), step_row["id"]),
        )
        connection.execute(
            "UPDATE workflow_executions SET status = 'PENDING', updated_at = ? WHERE id = ?",
            (utc_now(), execution_id),
        )
    else:
        connection.execute(
            """
            UPDATE execution_steps
            SET status = 'FAILED', error_message = ?, retry_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (error_message, utc_now(), step_row["id"]),
        )
        connection.execute(
            """
            UPDATE workflow_executions
            SET status = 'FAILED', error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (error_message, utc_now(), execution_id),
        )


def run_worker(database_path, stop_event):
    while not stop_event.is_set():
        try:
            execution = claim_execution(database_path)
            if execution:
                process_execution(database_path, execution["id"])
            else:
                time.sleep(0.25)
        except Exception:
            time.sleep(1)


def start_worker(app):
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_worker,
        args=(app.config["DATABASE_PATH"], stop_event),
        name="workflow-worker",
        daemon=True,
    )
    thread.start()
    app.extensions["workflow_worker_stop"] = stop_event

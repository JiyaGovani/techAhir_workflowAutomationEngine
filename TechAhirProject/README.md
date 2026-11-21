# Workflow Automation Engine

A local, modular Flask workflow engine using SQLite.

## Requirements

- Python 3.11 or newer
- SQLite 3 (included with Python)

## Setup

1. Create a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` if you want to customize `DATABASE_PATH`.

The SQLite database is created automatically from `migrations/schema.sql` when the application starts.

3. Start the application:

```powershell
python run.py
```

Open `http://localhost:5000`.

## Workflow Definition

Phase 1 supports `TASK`, `WAIT`, and `MESSAGE` steps.

```json
[
  {
    "type": "TASK",
    "task": "record_order_created",
    "config": {
      "order_id": "1001"
    }
  },
  {
    "type": "WAIT",
    "seconds": 30
  },
  {
    "type": "MESSAGE",
    "recipient": "customer@example.com",
    "content": "Thank you for your order"
  }
]
```

Available predefined tasks:

- `record_order_created`
- `record_inventory_update`

## Conditional Branching

An execution can provide top-level input data, such as `{"order_value": 600}`.
Supported CONDITION operators are `gt`, `gte`, `lt`, `lte`, `eq`, `ne`, and `in`.

```json
[
  {
    "type": "CONDITION",
    "field": "order_value",
    "operator": "gt",
    "value": 500,
    "true_next": 1,
    "false_next": null
  },
  {
    "type": "MESSAGE",
    "recipient": "customer@example.com",
    "content": "Your order qualifies for a follow-up"
  }
]
```

`true_next` and `false_next` are step indexes. A `null` target completes the workflow.

## Demonstration

1. Open the create-workflow page.
2. Enter a name and valid steps JSON.
3. Submit the workflow.
4. Select **Start workflow**.
5. Open the execution detail page.
6. Observe the TASK and MESSAGE states complete.
7. For a WAIT step, stop the server, leave it stopped past `resume_at`, restart it, and refresh the execution.

No WAIT step uses `time.sleep()`; it stores `resume_at` in SQLite and the worker returns to other executions until it is due.

For Phase 2 recovery tests:

1. Start a workflow containing a WAIT step.
2. Stop the server while the step is in `WAITING`.
3. Restart the server after `resume_at`.
4. Verify that the WAIT step completes and the next step runs once.
5. Repeat with a TASK or MESSAGE and confirm completed steps are not executed again.

MESSAGE rows use `step_id` as a unique idempotency key. The message insert and step completion occur in one SQLite transaction, preventing a duplicate message row if the process resumes after a crash.

## API

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/workflows` | List workflows |
| `POST` | `/api/workflows` | Create a workflow |
| `POST` | `/api/workflows/{id}/start` | Start an execution |
| `GET` | `/api/executions/{id}` | Inspect an execution and steps |

Create workflow example:

```json
{
  "name": "Order follow-up",
  "steps": [
    {
      "type": "TASK",
      "task": "record_order_created",
      "config": {
        "order_id": "1001"
      }
    },
    {
      "type": "WAIT",
      "seconds": 30
    },
    {
      "type": "MESSAGE",
      "recipient": "customer@example.com",
      "content": "Thank you for your order"
    }
  ]
}
```

## Tests

Run the unit suite:

```powershell
python -m pip install pytest
python -m pytest -q
```

Integration tests use a temporary SQLite database when database fixtures are added.

## Architecture

The application is a modular monolith:

- Flask routes accept workflow definitions and execution requests.
- Jinja2 templates provide the HTML interface.
- SQLite persists workflows, executions, steps, and simulated messages.
- A daemon worker thread claims executions and processes steps.
- The TASK service executes predefined Python functions.
- WAIT steps persist `resume_at` instead of blocking the worker.
- MESSAGE steps insert simulated records with an idempotency key.
- CONDITION steps evaluate simple fields and branch to step indexes.

## Persistence and Recovery

Every execution starts in `PENDING`, advances to `RUNNING`, and ends in `COMPLETED` or `FAILED`. Every step persists `PENDING`, `RUNNING`, `WAITING`, `COMPLETED`, or `FAILED`.

Before a step action, its row is persisted. The worker updates completed actions separately or as part of the same transaction. Completed steps are not rerun after restart.

For MESSAGE steps, the insert and step completion are in the same SQLite transaction. SQLite does not guarantee exactly-once delivery to an external service, because this project simulates messages in the database. It does guarantee no duplicate simulated message row from this engine for the same step.

## Retry Behavior

Recoverable exceptions retry the step using exponential delays. Default maximum attempts is 3. The retry timestamp is persisted, and the execution returns to `PENDING`. An exhausted step and execution become `FAILED`.

## API Examples

Start a workflow:

```powershell
curl.exe -X POST http://localhost:5000/api/workflows/1/start -H "Content-Type: application/json" -d "{\"input_data\":{\"order_value\":600}}"
```

Inspect an execution:

```powershell
curl.exe http://localhost:5000/api/executions/1
```

## Demonstration Recording Guide

1. Start the application.
2. Create a workflow using the visual step builder.
3. Start it with input `{"order_value": 600}`.
4. Show the execution changing from RUNNING to WAITING.
5. Stop the server and restart it.
6. Show that progress resumes from the persisted step.
7. Refresh the page and show one message row or completed message step.

## Limitations

- SQLite is not suitable for high-concurrency distributed deployment.
- There is no authentication or authorization.
- User input cannot register arbitrary Python code.
- Messages are simulated database records, not sent externally.
- Branching is limited to integer step indexes.
- The initial worker is in-process, not a distributed queue.
- Exactly-once external delivery is not claimed.

## Future Improvements

- Replace SQLite with PostgreSQL for stronger concurrency.
- Add durable scheduler tables and dispatch queues.
- Run distributed workers with database or queue leases.
- Add external message provider adapters.
- Add authentication, permissions, and execution audit logs.
- Add visual branch editing and cycle detection.
- Add metrics, structured logging, and dead-letter handling.

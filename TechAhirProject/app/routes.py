from flask import jsonify, redirect, render_template, request, url_for

from app.db import get_db


def rows_as_dicts(rows):
    return [dict(row) for row in rows]


def row_as_dict(row):
    return dict(row) if row is not None else None


def validate_steps(steps):
    if not isinstance(steps, list):
        return "Steps must be a JSON array."

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            return f"Step {index} must be a JSON object."

        step_type = step.get("type")
        if step_type not in {"TASK", "WAIT", "MESSAGE", "CONDITION"}:
            return f"Step {index} has an unsupported type."

        if step_type == "CONDITION":
            if not isinstance(step.get("field"), str):
                return f"Step {index} condition requires a field."
            if step.get("operator") not in {"gt", "gte", "lt", "lte", "eq", "ne", "in"}:
                return f"Step {index} has an unsupported condition operator."
            if "value" not in step:
                return f"Step {index} condition requires a value."
            for target_name in ("true_next", "false_next"):
                target = step.get(target_name)
                if target is not None:
                    if not isinstance(target, int):
                        return f"Step {index} {target_name} must be a step index or null."
                    if target < 0 or target >= len(steps):
                        return f"Step {index} {target_name} points outside the workflow."
    return None


def register_routes(app):
    @app.route("/")
    def index():
        db = get_db()
        cursor = db.execute(
            """
            SELECT w.id, w.name, w.created_at,
                   COUNT(we.id) AS execution_count
            FROM workflows w
            LEFT JOIN workflow_executions we ON we.workflow_id = w.id
            GROUP BY w.id, w.name, w.created_at
            ORDER BY w.created_at DESC
            """
        )
        workflows = rows_as_dicts(cursor.fetchall())

        return render_template("index.html", workflows=workflows)

    @app.route("/workflows/new")
    def new_workflow():
        return render_template("workflow_form.html")

    @app.route("/workflows", methods=["POST"])
    def create_workflow():
        db = get_db()
        name = request.form.get("name", "").strip()
        steps_text = request.form.get("steps", "").strip()

        if not name:
            return render_template(
                "workflow_form.html",
                error="Workflow name is required.",
                name=name,
                steps=steps_text,
            ), 400

        import json

        try:
            steps = json.loads(steps_text)
        except json.JSONDecodeError as error:
            return render_template(
                "workflow_form.html",
                error="Invalid JSON: " + str(error),
                name=name,
                steps=steps_text,
            ), 400

        validation_error = validate_steps(steps)
        if validation_error:
            return render_template(
                "workflow_form.html",
                error=validation_error,
                name=name,
                steps=steps_text,
            ), 400

        definition = {"steps": steps}
        cursor = db.execute(
            "INSERT INTO workflows (name, definition) VALUES (?, ?)",
            (name, json.dumps(definition)),
        )
        workflow_id = cursor.lastrowid
        db.commit()

        return redirect(url_for("workflow_detail", workflow_id=workflow_id))

    @app.route("/workflows/<int:workflow_id>")
    def workflow_detail(workflow_id):
        db = get_db()
        cursor = db.execute(
            "SELECT * FROM workflows WHERE id = ?",
            (workflow_id,),
        )
        workflow = row_as_dict(cursor.fetchone())
        if workflow is None:
            return "Workflow not found", 404

        cursor = db.execute(
            """
            SELECT * FROM workflow_executions
            WHERE workflow_id = ?
            ORDER BY created_at DESC
            """,
            (workflow_id,),
        )
        executions = rows_as_dicts(cursor.fetchall())

        return render_template(
            "workflow_detail.html",
            workflow=workflow,
            executions=executions,
        )

    @app.route("/workflows/<int:workflow_id>/start", methods=["POST"])
    def start_workflow(workflow_id):
        db = get_db()
        input_text = request.form.get("input_data", "{}").strip()
        import json
        try:
            input_data = json.loads(input_text)
        except json.JSONDecodeError:
            return "Invalid execution input JSON", 400
        if not isinstance(input_data, dict):
            return "Execution input must be a JSON object", 400

        cursor = db.execute(
            "SELECT id FROM workflows WHERE id = ?",
            (workflow_id,),
        )
        if cursor.fetchone() is None:
            return "Workflow not found", 404

        cursor = db.execute(
            """
            INSERT INTO workflow_executions (workflow_id, status, input_data)
            VALUES (?, 'PENDING', ?)
            """,
            (workflow_id, json.dumps(input_data)),
        )
        execution_id = cursor.lastrowid
        db.commit()

        return redirect(url_for("execution_detail", execution_id=execution_id))

    @app.route("/executions/<int:execution_id>")
    def execution_detail(execution_id):
        db = get_db()
        cursor = db.execute(
            """
            SELECT we.*, w.name AS workflow_name
            FROM workflow_executions we
            JOIN workflows w ON w.id = we.workflow_id
            WHERE we.id = ?
            """,
            (execution_id,),
        )
        execution = row_as_dict(cursor.fetchone())
        if execution is None:
            return "Execution not found", 404

        cursor = db.execute(
            """
            SELECT * FROM execution_steps
            WHERE execution_id = ?
            ORDER BY step_index
            """,
            (execution_id,),
        )
        steps = rows_as_dicts(cursor.fetchall())

        return render_template(
            "execution_detail.html",
            execution=execution,
            steps=steps,
        )

    @app.route("/api/workflows", methods=["GET", "POST"])
    def api_workflows():
        db = get_db()
        if request.method == "GET":
            cursor = db.execute("SELECT * FROM workflows ORDER BY created_at DESC")
            return jsonify(rows_as_dicts(cursor.fetchall()))

        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        steps = data.get("steps")
        if not name:
            return jsonify({"error": "name and a steps array are required"}), 400
        validation_error = validate_steps(steps)
        if validation_error:
            return jsonify({"error": validation_error}), 400

        import json

        cursor = db.execute(
            "INSERT INTO workflows (name, definition) VALUES (?, ?)",
            (name, json.dumps({"steps": steps})),
        )
        workflow_id = cursor.lastrowid
        cursor = db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        workflow = row_as_dict(cursor.fetchone())
        db.commit()
        return jsonify(workflow), 201

    @app.route("/api/workflows/<int:workflow_id>/start", methods=["POST"])
    def api_start_workflow(workflow_id):
        db = get_db()
        data = request.get_json(silent=True) or {}
        input_data = data.get("input_data", {})
        if not isinstance(input_data, dict):
            return jsonify({"error": "input_data must be a JSON object"}), 400

        import json
        cursor = db.execute(
            "SELECT id FROM workflows WHERE id = ?",
            (workflow_id,),
        )
        if cursor.fetchone() is None:
            return jsonify({"error": "Workflow not found"}), 404

        cursor = db.execute(
            """
            INSERT INTO workflow_executions (workflow_id, status, input_data)
            VALUES (?, 'PENDING', ?)
            """,
            (workflow_id, json.dumps(input_data)),
        )
        execution_id = cursor.lastrowid
        cursor = db.execute(
            "SELECT * FROM workflow_executions WHERE id = ?",
            (execution_id,),
        )
        execution = row_as_dict(cursor.fetchone())
        db.commit()
        return jsonify(execution), 201

    @app.route("/api/executions/<int:execution_id>")
    def api_execution_detail(execution_id):
        db = get_db()
        cursor = db.execute(
            "SELECT * FROM workflow_executions WHERE id = ?",
            (execution_id,),
        )
        execution = row_as_dict(cursor.fetchone())
        if execution is None:
            return jsonify({"error": "Execution not found"}), 404

        cursor = db.execute(
            """
            SELECT * FROM execution_steps
            WHERE execution_id = ?
            ORDER BY step_index
            """,
            (execution_id,),
        )
        steps = rows_as_dicts(cursor.fetchall())

        return jsonify({"execution": execution, "steps": steps})

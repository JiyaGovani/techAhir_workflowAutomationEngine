from flask import Flask

from config import Config
from app.db import init_database, get_db


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    init_database(app)

    with app.app_context():
        db = get_db()
        with app.open_resource("../migrations/schema.sql") as schema:
            db.executescript(schema.read().decode("utf-8"))

    from app.routes import register_routes

    register_routes(app)

    if test_config is None:
        from app.worker import start_worker

        start_worker(app)

    return app

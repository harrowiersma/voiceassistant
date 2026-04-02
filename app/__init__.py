import os
from flask import Flask
from db.init_db import init_db


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("app.config.Config")

    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    init_db(app.config["DATABASE"])

    from app.routes.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    return app

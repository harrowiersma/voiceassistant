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
    from app.routes.sip import bp as sip_bp
    from app.routes.ai import bp as ai_bp
    from app.routes.persona import bp as persona_bp
    from app.routes.knowledge import bp as knowledge_bp
    from app.routes.availability import bp as availability_bp
    from app.routes.calls import bp as calls_bp
    from app.routes.actions import bp as actions_bp
    from app.routes.system import bp as system_bp
    from app.routes.api import bp as api_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(sip_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(persona_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(availability_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(actions_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(api_bp)

    return app

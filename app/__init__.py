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

    from app.auth import bp as auth_bp
    from app.auth import login_required_hook
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.sip import bp as sip_bp
    from app.routes.ai import bp as ai_bp
    from app.routes.persona import bp as persona_bp
    from app.routes.personas import bp as personas_bp
    from app.routes.knowledge import bp as knowledge_bp
    from app.routes.availability import bp as availability_bp
    from app.routes.calls import bp as calls_bp
    from app.routes.actions import bp as actions_bp
    from app.routes.blocking import bp as blocking_bp
    from app.routes.persons import bp as persons_bp_route
    from app.routes.system import bp as system_bp
    from app.routes.api import bp as api_bp
    from app.routes.backup import bp as backup_bp
    from app.routes.google_oauth import bp as google_oauth_bp

    app.register_blueprint(auth_bp)
    app.before_request(login_required_hook)

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(sip_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(persona_bp)
    app.register_blueprint(personas_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(availability_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(actions_bp)
    app.register_blueprint(blocking_bp)
    app.register_blueprint(persons_bp_route)
    app.register_blueprint(system_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(google_oauth_bp)

    return app

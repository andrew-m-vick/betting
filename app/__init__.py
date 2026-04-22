"""Flask application factory."""
from __future__ import annotations

from flask import Flask

from config import Config, get_config

from .extensions import bcrypt, db, login_manager, migrate


def create_app(config_class: type[Config] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class or get_config())

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # Models must be imported so Flask-Migrate sees them during autogenerate.
    from . import models  # noqa: F401

    from .auth.routes import auth_bp
    from .bets.routes import bets_bp
    from .main.routes import main_bp
    from .odds.routes import odds_bp
    from .tools.routes import tools_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(odds_bp, url_prefix="/odds")
    app.register_blueprint(tools_bp)
    app.register_blueprint(bets_bp, url_prefix="/my-bets")

    from flask import render_template

    @app.errorhandler(404)
    def _404(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _500(e):
        return render_template("errors/500.html"), 500

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User

        return db.session.get(User, int(user_id))

    return app

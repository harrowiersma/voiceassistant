from flask import Blueprint, render_template
bp = Blueprint("persona", __name__)

@bp.route("/persona")
def index():
    return render_template("persona.html")

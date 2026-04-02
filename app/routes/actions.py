from flask import Blueprint, render_template
bp = Blueprint("actions", __name__)

@bp.route("/actions")
def index():
    return render_template("actions.html")

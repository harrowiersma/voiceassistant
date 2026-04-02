from flask import Blueprint, render_template
bp = Blueprint("ai", __name__)

@bp.route("/ai")
def index():
    return render_template("ai.html")

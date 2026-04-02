from flask import Blueprint, render_template
bp = Blueprint("knowledge", __name__)

@bp.route("/knowledge")
def index():
    return render_template("knowledge.html")

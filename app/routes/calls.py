from flask import Blueprint, render_template
bp = Blueprint("calls", __name__)

@bp.route("/calls")
def index():
    return render_template("calls.html")

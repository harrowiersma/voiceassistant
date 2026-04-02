from flask import Blueprint, render_template
bp = Blueprint("availability", __name__)

@bp.route("/availability")
def index():
    return render_template("availability.html")

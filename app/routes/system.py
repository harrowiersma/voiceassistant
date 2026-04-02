from flask import Blueprint, render_template
bp = Blueprint("system_mgmt", __name__)

@bp.route("/system")
def index():
    return render_template("system.html")

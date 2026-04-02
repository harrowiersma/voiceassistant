from flask import Blueprint, render_template
bp = Blueprint("sip", __name__)

@bp.route("/sip")
def index():
    return render_template("sip.html")

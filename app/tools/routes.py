"""Tools blueprint: EV Calculator and Parlay Simulator.

Both are stateless client-side tools. The server only renders the shell;
all math (and the Monte Carlo for parlays) runs in the browser so the
server stays fast and stateless.
"""
from flask import Blueprint, render_template

tools_bp = Blueprint("tools", __name__, template_folder="../templates/tools")


@tools_bp.route("/ev-calculator")
def ev_calculator():
    return render_template("tools/ev.html")


@tools_bp.route("/parlay-simulator")
def parlay_simulator():
    return render_template("tools/parlay.html")

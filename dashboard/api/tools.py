"""Tools API — exposes the Custodian tool registry over HTTP."""
from flask import Blueprint, jsonify, request
from custodian.tools.registry import default_registry

tools_bp = Blueprint("tools", __name__)
_registry = None


def get_registry():
    global _registry
    if _registry is None:
        _registry = default_registry().load()
    return _registry


@tools_bp.route("/list")
def tool_list():
    reg = get_registry()
    tools = [
        {
            "name": t.name,
            "description": t.description,
            "band": t.band,
            "band_label": t.band_label,
            "cost_usd": t.cost_usd,
            "configured": t.configured,
            "tags": t.tags,
            "version": t.version,
        }
        for t in reg.all()
    ]
    return jsonify({"tools": tools, **reg.summary()})


@tools_bp.route("/summary")
def tool_summary():
    return jsonify(get_registry().summary())

import os
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "asterisk")
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), keep_trailing_newline=True)


def _normalize_keys(config):
    """Convert dot-separated keys to underscore keys for Jinja2 templates."""
    return {k.replace(".", "_"): v for k, v in config.items()}


def render_pjsip_conf(config):
    """Render pjsip.conf from a config dict with sip.* keys."""
    template = _env.get_template("pjsip.conf.j2")
    return template.render(**_normalize_keys(config))


def render_extensions_conf(config):
    """Render extensions.conf from a config dict with sip.* keys."""
    template = _env.get_template("extensions.conf.j2")
    return template.render(**_normalize_keys(config))


def render_rtp_conf(config):
    """Render rtp.conf with STUN/ICE settings for NAT traversal."""
    template = _env.get_template("rtp.conf.j2")
    return template.render(**_normalize_keys(config))

/**
 * Shared status helper functions for Voice Secretary dashboard.
 * Used by dashboard.html and system.html.
 */

function statusDot(state) {
    var map = {
        "ok": "ok", "connected": "ok", "loaded": "ok", "running": "ok",
        "registered": "ok", "installed": "ok",
        "warn": "warn", "expiring": "warn",
        "error": "error", "failed": "error",
    };
    return map[state] || "idle";
}

function statusLabel(state) {
    return (state || "unknown").replace(/_/g, " ");
}

function progressClass(pct) {
    if (pct > 85) return "error";
    if (pct > 70) return "warn";
    return "ok";
}

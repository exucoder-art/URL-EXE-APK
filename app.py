"""
EXU URL-to-App Converter
Flask application entry point.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    abort,
)
from flask_cors import CORS
from werkzeug.utils import secure_filename
from PIL import Image

from config import Config
from backend.validators import (
    sanitize_url,
    validate_app_name,
    validate_package_name,
    validate_color,
    fetch_site_metadata,
)
from backend.build_manager import build_manager
from workers.builder import start_build_async

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
app.config.from_object(Config)
Config.init_app(app)

CORS(app, origins=Config.ALLOWED_ORIGINS, supports_credentials=True)


def client_ip() -> str:
    # Respect common proxy headers carefully
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


# ───────────────────────────── Pages ─────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ───────────────────────────── API ───────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "EXU URL-to-App Converter", "version": "1.0.0"})


@app.route("/api/validate-url", methods=["POST"])
def api_validate_url():
    data = request.get_json(silent=True) or {}
    raw = data.get("url", "").strip()
    clean = sanitize_url(raw)
    if not clean:
        return jsonify({"ok": False, "error": "Invalid or blocked URL. Only public http/https URLs are allowed."}), 400

    meta = fetch_site_metadata(clean)
    return jsonify({
        "ok": True,
        "url": clean,
        "metadata": {
            "title": meta.get("title") or "",
            "description": meta.get("description") or "",
            "favicon": meta.get("favicon") or "",
            "fetch_ok": meta.get("ok", False),
            "fetch_error": meta.get("error"),
        },
    })


@app.route("/api/build", methods=["POST"])
def api_build():
    # Accept both JSON and multipart (for icon upload)
    if request.content_type and "multipart/form-data" in request.content_type:
        url_raw = request.form.get("url", "")
        app_name = request.form.get("app_name", "")
        package_name = request.form.get("package_name", "")
        theme_color = request.form.get("theme_color", "#6366f1")
        targets_raw = request.form.get("targets", "apk,exe")
        icon_file = request.files.get("icon")
    else:
        data = request.get_json(silent=True) or {}
        url_raw = data.get("url", "")
        app_name = data.get("app_name", "")
        package_name = data.get("package_name", "")
        theme_color = data.get("theme_color", "#6366f1")
        targets_raw = data.get("targets", ["apk", "exe"])
        if isinstance(targets_raw, list):
            targets_raw = ",".join(targets_raw)
        icon_file = None

    # Validate URL
    url = sanitize_url(url_raw)
    if not url:
        return jsonify({"ok": False, "error": "Invalid or unsafe URL."}), 400

    # Validate app name
    ok, result = validate_app_name(app_name)
    if not ok:
        return jsonify({"ok": False, "error": result}), 400
    app_name = result

    # Package
    ok, result = validate_package_name(package_name)
    if not ok:
        return jsonify({"ok": False, "error": result}), 400
    package_name = result

    theme_color = validate_color(theme_color)

    # Targets
    allowed_targets = {"apk", "exe"}
    targets = [t.strip().lower() for t in targets_raw.split(",") if t.strip()]
    targets = [t for t in targets if t in allowed_targets]
    if not targets:
        return jsonify({"ok": False, "error": "Select at least one target: apk or exe."}), 400

    # Icon handling
    icon_path = None
    if icon_file and icon_file.filename:
        if not allowed_file(icon_file.filename):
            return jsonify({"ok": False, "error": "Icon must be PNG, JPG, JPEG, WEBP or ICO."}), 400
        try:
            img = Image.open(icon_file.stream)
            img.verify()  # security: ensure it's a real image
            icon_file.stream.seek(0)
            img = Image.open(icon_file.stream)
            # Resize to standard sizes
            img = img.convert("RGBA")
            img.thumbnail((512, 512), Image.Resampling.LANCZOS)
            fname = f"{uuid.uuid4().hex}.png"
            save_path = Config.UPLOAD_FOLDER / "icons" / fname
            img.save(save_path, format="PNG", optimize=True)
            icon_path = str(save_path.relative_to(Config.BASE_DIR))
        except Exception as e:
            return jsonify({"ok": False, "error": f"Invalid image file: {str(e)[:80]}"}), 400

    # Optional metadata refresh
    meta = fetch_site_metadata(url)

    job, err = build_manager.create_job(
        url=url,
        app_name=app_name,
        package_name=package_name,
        theme_color=theme_color,
        targets=targets,
        icon_path=icon_path,
        ip=client_ip(),
        metadata=meta,
    )
    if not job:
        return jsonify({"ok": False, "error": err}), 429

    # Kick off background worker
    start_build_async(job["id"])

    return jsonify({
        "ok": True,
        "job_id": job["id"],
        "status": job["status"],
        "message": "Build queued",
    }), 202


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    job = build_manager.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404

    return jsonify({
        "ok": True,
        "job": {
            "id": job["id"],
            "app_name": job["app_name"],
            "url": job["url"],
            "targets": job["targets"],
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "artifacts": job.get("artifacts", {}),
            "error": job.get("error"),
            "logs": job.get("logs", [])[-30:],  # last 30 log lines
        },
    })


@app.route("/api/download/<job_id>/<target>")
def api_download(job_id: str, target: str):
    target = target.lower()
    if target not in ("apk", "exe"):
        abort(400)

    job = build_manager.get_job(job_id)
    if not job:
        abort(404)
    if job["status"] != "completed":
        return jsonify({"ok": False, "error": "Build not ready"}), 400

    artifacts = job.get("artifacts", {})
    if target not in artifacts:
        abort(404)

    rel = artifacts[target]
    directory = Config.BUILD_FOLDER / Path(rel).parent
    filename = Path(rel).name

    # Security: ensure path stays inside BUILD_FOLDER
    try:
        full = (directory / filename).resolve()
        if not str(full).startswith(str(Config.BUILD_FOLDER.resolve())):
            abort(403)
    except Exception:
        abort(403)

    mime = "application/vnd.android.package-archive" if target == "apk" else "application/octet-stream"
    return send_from_directory(
        directory,
        filename,
        as_attachment=True,
        download_name=filename,
        mimetype=mime,
    )


@app.route("/api/recent")
def api_recent():
    return jsonify({"ok": True, "jobs": build_manager.list_recent(15)})


# ───────────────────────────── Error handlers ────────────────────

@app.errorhandler(413)
def too_large(e):
    return jsonify({"ok": False, "error": "File too large (max 16 MB)"}), 413


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Not found"}), 404
    return render_template("index.html"), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)

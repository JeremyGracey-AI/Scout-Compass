"""Flask web UI for Scout Skill Forge.

Run:
    cd scout-skill-forge
    pip install flask pyyaml jinja2
    python web/app.py
    # open http://127.0.0.1:5000

Endpoints:
    GET  /              -> form
    GET  /api/personas  -> list personas
    POST /generate      -> render skill(s) and return preview JSON
    POST /download      -> render skill(s) and return a zip
"""
from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

# Make CLI module importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "cli"))


def _load_env_file(path: Path) -> None:
    """Minimal .env loader (no dependency) so local dev can set Supabase config."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file(Path(__file__).resolve().parent / ".env")

# Frontend config (safe to expose). When unset, the app runs without accounts —
# the persona library + sign-in simply stay hidden. The publishable key is RLS-gated.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

from skill_forge import (  # noqa: E402
    PERSONAS_DIR,
    WORKFLOWS,
    load_persona,
    persona_from_data,
    render_skill,
    validate_skill_md,
)
import automations  # noqa: E402

app = Flask(__name__, template_folder="templates", static_folder="static")


def _persona_summary(path: Path) -> dict:
    p = load_persona(path)
    return {
        "file": path.name,
        "id": p.id,
        "display_name": p.display_name,
        "title": p.title,
        "org": p.org,
    }


@app.route("/")
def index():
    personas = [_persona_summary(p) for p in sorted(PERSONAS_DIR.glob("*.yaml"))]
    workflows = [
        {"id": k, "label": v["title_suffix"]} for k, v in WORKFLOWS.items()
    ]
    return render_template(
        "index.html",
        personas=personas,
        workflows=workflows,
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_ANON_KEY,
    )


@app.route("/api/personas")
def api_personas():
    return jsonify([_persona_summary(p) for p in sorted(PERSONAS_DIR.glob("*.yaml"))])


def _render_batch(persona_file: str, workflows: list[str], prefix: str | None) -> list[dict]:
    persona_path = PERSONAS_DIR / persona_file
    persona = load_persona(persona_path)
    slug_prefix = (prefix or persona.first_name).lower().strip().replace(" ", "-")
    out = []
    for wf in workflows:
        if wf not in WORKFLOWS:
            continue
        slug = f"{slug_prefix}-{WORKFLOWS[wf]['default_slug_suffix']}"
        content = render_skill(workflow=wf, persona=persona, slug=slug)
        report = validate_skill_md(
            content, expected_slug=slug, exec_name=persona.first_name
        )
        out.append(
            {
                "workflow": wf,
                "slug": slug,
                "filename": f"{slug}/SKILL.md",
                "content": content,
                "valid": report.ok,
                "errors": report.errors,
                "warnings": report.warnings,
            }
        )
    return out


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True)
    persona_file = data.get("persona")
    workflows = data.get("workflows", [])
    prefix = data.get("prefix")
    if not persona_file or not workflows:
        return jsonify({"error": "persona and workflows are required"}), 400
    try:
        results = _render_batch(persona_file, workflows, prefix)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"results": results})


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(force=True)
    persona_file = data.get("persona")
    workflows = data.get("workflows", [])
    prefix = data.get("prefix")
    if not persona_file or not workflows:
        return jsonify({"error": "persona and workflows are required"}), 400

    results = _render_batch(persona_file, workflows, prefix)
    persona = load_persona(PERSONAS_DIR / persona_file)
    autos = automations.build_automations(persona, workflows, prefix=prefix)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            zf.writestr(r["filename"], r["content"])
        for a in autos:
            zf.writestr(
                f"automations/{automations.slugify(a.name)}.automation.yaml",
                automations.render_automation_yaml(a),
            )
        if autos:
            zf.writestr("automations/manifest.json", automations.render_manifest(autos))
            zf.writestr("automations/SETUP.md", automations.render_setup_md(autos))
        zf.writestr(
            "README.txt",
            "Drop the skill folders into ~/.copilot/skills/ on the machine running "
            "Microsoft Scout. Each subfolder contains a SKILL.md that Scout discovers "
            "automatically on the next conversation.\n\n"
            "The automations/ folder holds Scout automation definitions. See "
            "automations/SETUP.md to add them (import, or paste into Automations > New "
            "automation).\n",
        )
    buf.seek(0)
    zip_name = f"{(prefix or 'exec').lower()}-scout-skills.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_name,
    )


# --------------------------------------------------------------------------- #
# v1 app API: build from an inline (form) persona or a saved one. The browser
# does the install/manage via the File System Access API; the server only renders.
# --------------------------------------------------------------------------- #
def _persona_from_payload(data: dict):
    """Build a Persona from an inline form dict (`persona_data`) or a saved file (`persona`)."""
    inline = data.get("persona_data")
    if inline:
        return persona_from_data(inline, source="form")
    persona_file = data.get("persona")
    if persona_file:
        return load_persona(PERSONAS_DIR / persona_file)
    raise ValueError("Provide persona fields or choose a saved persona.")


def _skill_results(persona, workflows: list[str], prefix: str | None) -> list[dict]:
    slug_prefix = (prefix or persona.first_name).lower().strip().replace(" ", "-")
    results = []
    for wf in workflows:
        if wf not in WORKFLOWS:
            continue
        slug = f"{slug_prefix}-{WORKFLOWS[wf]['default_slug_suffix']}"
        content = render_skill(workflow=wf, persona=persona, slug=slug)
        report = validate_skill_md(content, expected_slug=slug, exec_name=persona.first_name)
        results.append(
            {
                "workflow": wf,
                "slug": slug,
                "path": f"{slug}/SKILL.md",
                "content": content,
                "valid": report.ok,
                "errors": report.errors,
                "warnings": report.warnings,
            }
        )
    return results


def _automation_files(persona, workflows: list[str], prefix: str | None) -> list[dict]:
    autos = automations.build_automations(persona, workflows, prefix=prefix)
    files = [
        {
            "filename": f"{automations.slugify(a.name)}.automation.yaml",
            "content": automations.render_automation_yaml(a),
        }
        for a in autos
    ]
    if autos:
        files.append({"filename": "manifest.json", "content": automations.render_manifest(autos)})
        files.append({"filename": "SETUP.md", "content": automations.render_setup_md(autos)})
    return files


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(force=True)
    workflows = data.get("workflows", [])
    prefix = data.get("prefix")
    if not workflows:
        return jsonify({"error": "Select at least one workflow."}), 400
    try:
        persona = _persona_from_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(
        {
            "skills": _skill_results(persona, workflows, prefix),
            "automations": _automation_files(persona, workflows, prefix),
        }
    )


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True)
    workflows = data.get("workflows", [])
    prefix = data.get("prefix")
    if not workflows:
        return jsonify({"error": "Select at least one workflow."}), 400
    try:
        persona = _persona_from_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    skills = _skill_results(persona, workflows, prefix)
    autos = _automation_files(persona, workflows, prefix)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for s in skills:
            zf.writestr(s["path"], s["content"])
        for f in autos:
            zf.writestr(f"automations/{f['filename']}", f["content"])
        zf.writestr(
            "README.txt",
            "Drop the skill folders into ~/.copilot/skills/ on the machine running "
            "Microsoft Scout. See automations/SETUP.md to add the automations.\n",
        )
    buf.seek(0)
    name = (prefix or persona.first_name or "exec").lower().strip().replace(" ", "-")
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"{name}-scout-skills.zip",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

"""Flask web UI for Scout Compass.

Run:
    cd scout-compass
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

import yaml
from flask import Flask, Response, jsonify, render_template, request, send_file

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

from compass import (  # noqa: E402
    PERSONAS_DIR,
    WORKFLOWS,
    load_persona,
    persona_from_data,
    render_skill,
    validate_skill_md,
)
import automations  # noqa: E402

app = Flask(__name__, template_folder="templates", static_folder="static")

# Presentation metadata for the skills picker + catalog (web only; the generator
# in cli/ stays the source of truth for how each archetype renders). Any archetype
# not listed here still works — index() falls back to label-only, category "Other".
WORKFLOW_META = {
    "briefing": {
        "blurb": "One-page exec brief — KPI table, who's in the room, talking points.",
        "triggers": ["brief me on", "prep me for", "give me a pre-read on"],
        "recurring": False, "category": "Prep & brief",
    },
    "meeting-prep": {
        "blurb": "Run-of-show for a specific meeting — agenda, attendees, decisions to land.",
        "triggers": ["prep me for my meeting with", "build an agenda for", "run of show for"],
        "recurring": False, "category": "Prep & brief",
    },
    "one-on-one": {
        "blurb": "1:1 prep card — since last time, follow-ups both ways, one growth note.",
        "triggers": ["prep for my 1:1 with", "follow-ups from my last 1:1 with"],
        "recurring": True, "category": "Prep & brief",
    },
    "comms": {
        "blurb": "Audience-mode draft with three subject lines and risk flags.",
        "triggers": ["draft", "reply to", "send a note to"],
        "recurring": False, "category": "Communicate",
    },
    "triage": {
        "blurb": "Daily/weekly digest — top-of-mind, compliance flags, KPI exceptions, delegations.",
        "triggers": ["morning digest", "what needs me today", "triage my inbox"],
        "recurring": True, "category": "Operate",
    },
    "decisions-log": {
        "blurb": "Durable decision record — the call, options, owner, follow-ups, review date.",
        "triggers": ["log this decision", "record what we decided", "what did we decide about"],
        "recurring": False, "category": "Operate",
    },
    "strategy": {
        "blurb": "Two-to-four page memo — recommendation, options table, sequencing, open questions.",
        "triggers": ["analyze", "build the case for", "strategic view on"],
        "recurring": False, "category": "Decide & review",
    },
    "review-prep": {
        "blurb": "MBR/QBR pack — KPI scorecard, narrative, wins, risks with recovery owners.",
        "triggers": ["prep my QBR", "build my monthly business review", "pull my KPI scorecard"],
        "recurring": True, "category": "Decide & review",
    },
}

# One-click presets: a named bundle of archetypes for a common executive mode.
WORKFLOW_PRESETS = [
    {"id": "daily", "label": "Daily driver",
     "description": "Everyday cockpit: triage, briefings, and 1:1 prep.",
     "workflows": ["triage", "briefing", "one-on-one"]},
    {"id": "meetings", "label": "Meetings & decisions",
     "description": "Walk in ready, walk out with the decision logged.",
     "workflows": ["meeting-prep", "one-on-one", "decisions-log"]},
    {"id": "review", "label": "Leadership review",
     "description": "Business reviews and the strategy + decisions behind them.",
     "workflows": ["review-prep", "strategy", "decisions-log"]},
    {"id": "all", "label": "The works",
     "description": "All eight archetypes.",
     "workflows": list(WORKFLOWS.keys())},
]


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
    workflows = []
    for k, v in WORKFLOWS.items():
        meta = WORKFLOW_META.get(k, {})
        workflows.append({
            "id": k,
            "label": v["title_suffix"],
            "blurb": meta.get("blurb", ""),
            "triggers": meta.get("triggers", []),
            "recurring": meta.get("recurring", False),
            "category": meta.get("category", "Other"),
        })
    return render_template(
        "index.html",
        personas=personas,
        workflows=workflows,
        presets=WORKFLOW_PRESETS,
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_ANON_KEY,
    )


@app.route("/api/personas")
def api_personas():
    return jsonify([_persona_summary(p) for p in sorted(PERSONAS_DIR.glob("*.yaml"))])


@app.route("/api/validate", methods=["POST"])
def api_validate():
    """Validate a SKILL.md body — used by the installed-skills manager for status."""
    data = request.get_json(force=True)
    content = data.get("content", "") or ""
    slug = data.get("slug") or None
    report = validate_skill_md(content, expected_slug=slug)
    return jsonify({"valid": report.ok, "errors": report.errors, "warnings": report.warnings})


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


# --------------------------------------------------------------------------- #
# Persona export: download what the builder produced (or a saved persona) as a
# ready-to-commit personas/<id>.yaml. Stateless — validates and serializes, but
# stores nothing, so a browser-built executive can be seeded into the repo.
# --------------------------------------------------------------------------- #
def _prune_empty(value):
    """Drop empty strings / lists / dicts so the exported YAML stays tidy.

    Run only after persona validation, which guarantees the required fields are
    present and non-empty — so they are never pruned.
    """
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            pruned = _prune_empty(item)
            if pruned not in ("", [], {}, None):
                cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        kept = (_prune_empty(item) for item in value)
        return [item for item in kept if item not in ("", [], {}, None)]
    return value


def _persona_yaml_text(raw: dict) -> str:
    """Serialize a (validated) persona mapping to commit-ready YAML with a header."""
    key_order = (
        "id", "display_name", "title", "org", "charter", "scope", "priorities",
        "voice_and_style", "decision_filters", "people", "delegates", "cadence",
        "escalation_rules", "automations", "provenance",
    )
    ordered = {k: raw[k] for k in key_order if k in raw}
    ordered.update({k: v for k, v in raw.items() if k not in ordered})  # keep any extras
    body = yaml.safe_dump(_prune_empty(ordered), sort_keys=False, allow_unicode=True)
    return (
        f"# Persona: {raw.get('display_name', 'Untitled')}\n"
        "# Generated by the Scout Compass builder. Edit freely, save under personas/,\n"
        "# then run: python cli/compass.py --persona personas/<this-file>.yaml\n"
        f"{body}"
    )


@app.route("/api/persona-yaml", methods=["POST"])
def api_persona_yaml():
    """Export the current persona as a downloadable personas/<id>.yaml file.

    A built (inline ``persona_data``) persona is validated, then emitted as YAML
    that ``load_persona`` can read back. A saved persona is returned verbatim so
    its curation and comments are preserved.
    """
    data = request.get_json(force=True)
    inline = data.get("persona_data")
    if inline:
        try:
            persona = persona_from_data(inline, source="form")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        filename = f"{automations.slugify(persona.id)}.yaml"
        return Response(
            _persona_yaml_text(inline),
            mimetype="application/x-yaml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    persona_file = data.get("persona")
    if not persona_file:
        return jsonify({"error": "Provide persona fields or choose a saved persona."}), 400
    # Saved persona: return the curated file as-is, guarded against path traversal.
    path = (PERSONAS_DIR / persona_file).resolve()
    if path.parent != PERSONAS_DIR.resolve() or path.suffix != ".yaml" or not path.exists():
        return jsonify({"error": "Unknown saved persona."}), 400
    return Response(
        path.read_text(encoding="utf-8"),
        mimetype="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

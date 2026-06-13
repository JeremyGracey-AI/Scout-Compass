"""Tests for compass: validator rules, persona schema, and render round-trip.

Run with: pytest  (pyproject sets pythonpath = ["cli"]).
"""
from __future__ import annotations

import textwrap

import pytest

import automations as auto
import compass as sf


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
VALID_DESCRIPTION = (
    'Prepares demo material for Morgan. Use when Morgan asks to "brief me," '
    '"prep me," or "update me." Always grounded.'
)

VALID_BODY = textwrap.dedent(
    """\
    # Morgan's Demo

    You are doing X for **Morgan Reyes**, General Manager.

    Use WorkIQ and the `m365_*` tools for context.

    ## Quality bar — self-check
    - [ ] one
    - [ ] two
    - [ ] three
    - [ ] four
    - [ ] five
    """
)


def make_skill(*, name: str | None = "demo-skill", description: str = VALID_DESCRIPTION,
               body: str = VALID_BODY) -> str:
    """Build a SKILL.md string. Pass name=None to omit the (optional) name field."""
    name_line = f"name: {name}\n" if name is not None else ""
    return f"---\n{name_line}description: '{description}'\n---\n\n{body}"


# --------------------------------------------------------------------------- #
# Frontmatter / spec rules
# --------------------------------------------------------------------------- #
def test_nameless_skill_is_valid():
    """The only required frontmatter field is description; name is optional."""
    report = sf.validate_skill_md(make_skill(name=None))
    assert report.ok
    assert report.errors == []


def test_missing_description_errors():
    content = f"---\nname: demo-skill\n---\n\n{VALID_BODY}"
    report = sf.validate_skill_md(content)
    assert not report.ok
    assert any("description" in e for e in report.errors)


def test_name_must_match_folder():
    report = sf.validate_skill_md(make_skill(name="morgan-briefing"),
                                  expected_slug="morgan-comms")
    assert not report.ok
    assert any("match the skill folder" in e for e in report.errors)


def test_name_matching_folder_is_ok():
    report = sf.validate_skill_md(make_skill(name="demo-skill"),
                                  expected_slug="demo-skill")
    assert report.ok


def test_bad_slug_name_errors():
    report = sf.validate_skill_md(make_skill(name="Demo_Skill"))
    assert not report.ok
    assert any("lowercase" in e for e in report.errors)


def test_missing_frontmatter_errors():
    report = sf.validate_skill_md("no frontmatter here")
    assert not report.ok


# --------------------------------------------------------------------------- #
# Body quality rules
# --------------------------------------------------------------------------- #
def test_filler_phrase_errors():
    body = VALID_BODY + "\nJust be helpful and do your best.\n"
    report = sf.validate_skill_md(make_skill(body=body))
    assert not report.ok
    assert any("filler" in e.lower() for e in report.errors)


def test_too_few_checklist_items_errors():
    body = "# Morgan's Demo\n\nMorgan. WorkIQ.\n\n## Quality bar\n- [ ] only one\n"
    report = sf.validate_skill_md(make_skill(body=body))
    assert not report.ok
    assert any("checklist" in e for e in report.errors)


def test_exec_name_required_when_supplied():
    body = VALID_BODY.replace("Morgan Reyes", "the executive").replace("Morgan's", "The")
    report = sf.validate_skill_md(make_skill(body=body), exec_name="Morgan")
    assert not report.ok
    assert any("not named in the first 200 words" in e for e in report.errors)


def test_long_description_warns_but_passes():
    long_desc = 'Morgan. Use when Morgan asks "a," "b," or "c." ' + ("x" * 1300)
    report = sf.validate_skill_md(make_skill(description=long_desc))
    assert report.ok  # warning, not error
    assert any("chars" in w for w in report.warnings)


def test_few_trigger_phrases_warns():
    report = sf.validate_skill_md(make_skill(description='Morgan does a thing for Morgan.'))
    assert report.ok
    assert any("trigger" in w for w in report.warnings)


def test_no_scout_tool_warns():
    body = VALID_BODY.replace("Use WorkIQ and the `m365_*` tools for context.", "Do the work.")
    report = sf.validate_skill_md(make_skill(body=body))
    assert report.ok
    assert any("Scout capability" in w for w in report.warnings)


def test_slug_regex():
    assert sf.SLUG_RE.match("morgan-briefing")
    assert not sf.SLUG_RE.match("Morgan")      # uppercase
    assert not sf.SLUG_RE.match("ab")          # too short
    assert not sf.SLUG_RE.match("-lead")       # leading hyphen


# --------------------------------------------------------------------------- #
# Persona schema
# --------------------------------------------------------------------------- #
def _full_persona() -> dict:
    return {
        "id": "x",
        "display_name": "Jane Doe",
        "title": "GM",
        "org": "Contoso Ltd.",
        "charter": "Lead things.",
        "scope": {"process_domains": ["Q2C"], "partner_orgs": ["Finance"]},
        "voice_and_style": {"tone": "calm", "signature_phrases": ["at scale"]},
        "decision_filters": ["Does it move a KPI?"],
    }


def test_validate_persona_accepts_full():
    assert sf.validate_persona(_full_persona()) == []


def test_validate_persona_flags_gaps():
    errors = sf.validate_persona({"id": "x"})
    assert any("display_name" in e for e in errors)
    assert any("process_domains" in e for e in errors)
    assert any("decision_filters" in e for e in errors)


def test_validate_persona_rejects_nonmapping():
    assert sf.validate_persona([1, 2, 3])
    assert sf.validate_persona(None)


def test_load_seed_persona():
    path = sf.PERSONAS_DIR / "morgan_reyes.yaml"
    if not path.exists():
        pytest.skip("Morgan persona not present")
    persona = sf.load_persona(path)
    assert persona.first_name == "Morgan"
    assert persona.partner_orgs  # non-empty


def test_persona_from_data_raises_on_sparse():
    # No disk I/O: exercise the validate-and-raise path directly.
    with pytest.raises(ValueError) as exc:
        sf.persona_from_data({"id": "x", "display_name": "Y"}, source="sparse")
    assert "is invalid" in str(exc.value)


# --------------------------------------------------------------------------- #
# Render round-trip: every archetype renders to a clean, valid skill
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("workflow", list(sf.WORKFLOWS))
def test_render_all_workflows_validate_clean(workflow):
    path = sf.PERSONAS_DIR / "morgan_reyes.yaml"
    if not path.exists():
        pytest.skip("Morgan persona not present")
    persona = sf.load_persona(path)
    slug = f"{persona.first_name.lower()}-{sf.WORKFLOWS[workflow]['default_slug_suffix']}"
    content = sf.render_skill(workflow=workflow, persona=persona, slug=slug)
    report = sf.validate_skill_md(content, expected_slug=slug, exec_name=persona.first_name)
    assert report.errors == []
    assert report.warnings == []


# --------------------------------------------------------------------------- #
# P4: persona grounding (optional fields, provenance, enrichment fallback)
# --------------------------------------------------------------------------- #
def _base_persona_dict() -> dict:
    return {
        "id": "dana",
        "display_name": "Dana Lin",
        "title": "VP, Platform",
        "org": "Contoso",
        "charter": "Lead the platform org.",
        "scope": {"process_domains": ["Reliability"], "partner_orgs": ["Finance"]},
        "voice_and_style": {"tone": "Direct", "signature_phrases": ["ship it"]},
        "decision_filters": ["Does it cut toil?"],
    }


def test_validate_persona_accepts_grounding_fields():
    data = _base_persona_dict()
    data.update(
        people={"chief_of_staff": "Priya Rao", "direct_reports": ["Lee — EM"]},
        delegates=[{"name": "Lee Park", "domains": ["triage"]}],
        cadence={"timezone": "ET"},
        escalation_rules=["Sev1 pages me anytime"],
        provenance={"source": "user", "confirmed": ["title"]},
    )
    assert sf.validate_persona(data) == []


def test_validate_persona_flags_bad_delegates():
    data = _base_persona_dict()
    data["delegates"] = ["not-a-mapping"]
    assert any("delegates" in e for e in sf.validate_persona(data))


def test_validate_persona_flags_bad_people_list():
    data = _base_persona_dict()
    data["people"] = {"direct_reports": "should-be-a-list"}
    assert any("direct_reports" in e for e in sf.validate_persona(data))


def test_render_grounding_enriched():
    data = _base_persona_dict()
    data.update(
        people={"chief_of_staff": "Priya Rao"},
        delegates=[{"name": "Lee Park", "domains": ["calendar triage"]}],
        cadence={"timezone": "ET", "working_hours": "9-5 ET"},
    )
    out = sf.render_skill(workflow="triage", persona=sf.persona_from_data(data), slug="dana-triage")
    assert "Chief of staff:** Priya Rao" in out
    assert "Lee Park" in out
    assert "cadence & boundaries" in out


def test_render_grounding_fallback_when_no_people():
    out = sf.render_skill(
        workflow="briefing", persona=sf.persona_from_data(_base_persona_dict()), slug="dana-briefing"
    )
    assert "Support team not yet on file" in out
    assert "people search" in out


# --------------------------------------------------------------------------- #
# Scout automation export
# --------------------------------------------------------------------------- #
def test_resolve_timezone():
    assert auto.resolve_timezone("Pacific (PT) — Redmond, WA") == "America/Los_Angeles"
    assert auto.resolve_timezone("ET") == "America/New_York"
    assert auto.resolve_timezone("Asia/Tokyo") == "Asia/Tokyo"  # unknown -> passthrough


def test_build_triage_automations():
    data = _base_persona_dict()
    data["display_name"] = "Morgan Reyes"
    data["cadence"] = {"timezone": "Pacific (PT)"}
    autos = auto.build_automations(sf.persona_from_data(data), ["triage"])
    assert len(autos) == 3
    assert all("Morgan" in a.name for a in autos)
    assert all(a.skill == "morgan-triage" for a in autos)
    crons = {a.cron for a in autos}
    assert {"30 6 * * 1-5", "30 17 * * 1-5", "0 17 * * 0"} == crons


def test_automation_to_doc_has_documented_fields():
    a = auto.Automation(name="X", prompt="do it", schedule_label="Every weekday at 6:30 AM", cron="30 6 * * 1-5")
    doc = auto.automation_to_doc(a)
    for key in ("name", "prompt", "trigger", "schedule", "condition", "oneShot"):
        assert key in doc
    assert doc["x_generator"]["cron"] == "30 6 * * 1-5"


def test_render_setup_and_manifest():
    a = auto.Automation(
        name="Morgan — morning digest", prompt="Run my morning triage digest.",
        schedule_label="Every weekday at 6:30 AM", cron="30 6 * * 1-5", skill="morgan-triage",
    )
    md = auto.render_setup_md([a])
    assert "Morgan — morning digest" in md and "Run my morning triage digest." in md
    manifest = auto.render_manifest([a])
    assert "morgan-triage" in manifest and "automations" in manifest


def test_persona_declared_automations_included():
    data = _base_persona_dict()
    data["automations"] = [
        {"name": "Weekly KPI sweep", "prompt": "Pull KPI exceptions.", "schedule": "Mon 9am", "cron": "0 9 * * 1"}
    ]
    autos = auto.build_automations(sf.persona_from_data(data), [])  # no triage; explicit only
    assert len(autos) == 1 and autos[0].name == "Weekly KPI sweep"


def test_validate_persona_flags_bad_automations():
    data = _base_persona_dict()
    data["automations"] = [{"prompt": "missing a name"}]
    assert any("automations" in e for e in sf.validate_persona(data))


def test_no_triage_yields_no_default_automations():
    assert auto.build_automations(sf.persona_from_data(_base_persona_dict()), ["briefing"]) == []


# --------------------------------------------------------------------------- #
# Web app smoke test (skipped if Flask isn't installed)
# --------------------------------------------------------------------------- #
def test_web_app_inline_generate():
    pytest.importorskip("flask")
    import sys
    from pathlib import Path

    # Import web/app.py the same way Vercel / the server do, so Flask resolves its
    # template root correctly (it derives root_path from the module in sys.modules).
    web_dir = Path(sf.__file__).resolve().parent.parent / "web"
    sys.path.insert(0, str(web_dir))
    import app as web  # noqa: web/app.py
    client = web.app.test_client()

    assert client.get("/").status_code == 200

    r = client.post("/api/generate", json={"persona_data": _base_persona_dict(), "workflows": ["briefing", "triage"]})
    assert r.status_code == 200
    body = r.get_json()
    assert [s["workflow"] for s in body["skills"]] == ["briefing", "triage"]
    assert all(s["valid"] for s in body["skills"])
    assert any(f["filename"] == "SETUP.md" for f in body["automations"])

    bad = client.post("/api/generate", json={"persona_data": {"display_name": "X"}, "workflows": ["briefing"]})
    assert bad.status_code == 400


def test_web_app_persona_yaml_export():
    pytest.importorskip("flask")
    import sys
    from pathlib import Path
    import yaml as _yaml

    web_dir = Path(sf.__file__).resolve().parent.parent / "web"
    sys.path.insert(0, str(web_dir))
    import app as web  # noqa: web/app.py
    client = web.app.test_client()

    # A built (inline) persona exports as YAML that round-trips back into a Persona.
    r = client.post("/api/persona-yaml", json={"persona_data": _base_persona_dict()})
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    text = r.get_data(as_text=True)
    persona = sf.persona_from_data(_yaml.safe_load(text))  # raises if the export is invalid
    assert persona.display_name == "Dana Lin"
    assert "decision_filters" in text

    # An invalid persona is rejected, not silently exported.
    bad = client.post("/api/persona-yaml", json={"persona_data": {"display_name": "X"}})
    assert bad.status_code == 400


def test_web_app_validate_endpoint():
    pytest.importorskip("flask")
    import sys
    from pathlib import Path

    web_dir = Path(sf.__file__).resolve().parent.parent / "web"
    sys.path.insert(0, str(web_dir))
    import app as web  # noqa: web/app.py
    client = web.app.test_client()

    # A cleanly generated skill validates with no errors or warnings.
    persona = sf.persona_from_data(_base_persona_dict())
    slug = "dana-briefing"
    content = sf.render_skill(workflow="briefing", persona=persona, slug=slug)
    r = client.post("/api/validate", json={"content": content, "slug": slug})
    assert r.status_code == 200
    rep = r.get_json()
    assert rep["valid"] and rep["errors"] == []

    # A junk body is reported invalid, not accepted.
    bad = client.post("/api/validate", json={"content": "no frontmatter", "slug": "x"})
    assert bad.get_json()["valid"] is False

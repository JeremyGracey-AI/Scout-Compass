"""compass.py — Microsoft Scout SKILL.md generator for executive personas.

Generates persona-grounded SKILL.md files for Microsoft Scout
(~/.copilot/skills/<skill-name>/SKILL.md) tailored to a specific executive.

Usage (interactive):
    python compass.py

Usage (non-interactive):
    python compass.py \
        --persona personas/morgan_reyes.yaml \
        --workflows briefing,comms,triage,strategy \
        --out ~/.copilot/skills \
        --prefix morgan

Usage (validate only):
    python compass.py --validate ~/.copilot/skills/morgan-briefing/SKILL.md
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml jinja2")

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml jinja2")

import automations  # sibling module (cli/); safe — it imports compass only for typing


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
PERSONAS_DIR = PROJECT_ROOT / "personas"

# Default Scout skills directory — see
# https://learn.microsoft.com/en-us/microsoft-scout/use-microsoft-scout#create-a-custom-skill
DEFAULT_SCOUT_SKILLS_DIR = Path.home() / ".copilot" / "skills"

WORKFLOWS = {
    "briefing": {
        "template": "briefing.md.j2",
        "title_suffix": "Executive Briefing",
        "default_slug_suffix": "briefing",
    },
    "comms": {
        "template": "comms.md.j2",
        "title_suffix": "Executive Communications",
        "default_slug_suffix": "comms",
    },
    "triage": {
        "template": "triage.md.j2",
        "title_suffix": "Inbox & Calendar Triage",
        "default_slug_suffix": "triage",
    },
    "strategy": {
        "template": "strategy.md.j2",
        "title_suffix": "Strategic Analysis Memo",
        "default_slug_suffix": "strategy",
    },
    "meeting-prep": {
        "template": "meeting-prep.md.j2",
        "title_suffix": "Meeting Prep",
        "default_slug_suffix": "meeting-prep",
    },
    "decisions-log": {
        "template": "decisions-log.md.j2",
        "title_suffix": "Decisions Log",
        "default_slug_suffix": "decisions-log",
    },
    "one-on-one": {
        "template": "one-on-one.md.j2",
        "title_suffix": "1:1 Prep",
        "default_slug_suffix": "one-on-one",
    },
    "review-prep": {
        "template": "review-prep.md.j2",
        "title_suffix": "Business Review Prep",
        "default_slug_suffix": "review-prep",
    },
}


# -- Validation rules from the Scout / Agent Skills SKILL.md spec ----------
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
MAX_DESCRIPTION_CHARS = 1200  # soft ceiling; long descriptions hurt skill matching
MAX_BODY_BYTES = 1_000_000

# -- Quality-bar rules enforced on the body (the meta-skill's checklist, in code) --
MIN_TRIGGER_PHRASES = 3
MIN_CHECKLIST_ITEMS = 5
# Phrases that signal a low-effort, ungrounded skill. Hard-fail the worst; warn on the rest.
FILLER_ERROR = ("be helpful", "do your best")
FILLER_WARN = ("as needed", "as appropriate")
# At least one real Scout capability should appear in the body.
SCOUT_TOOL_HINTS = ("m365_", "workiq", "people search")
# Quoted trigger phrases in the description, e.g. "brief me on".
TRIGGER_RE = re.compile(r'"[^"]+"')
# Markdown task-list checkboxes: "- [ ] ...".
CHECKBOX_RE = re.compile(r"(?m)^\s*-\s\[ \]\s")


@dataclass
class ValidationReport:
    """Outcome of validating a SKILL.md. ``errors`` block; ``warnings`` advise."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class Persona:
    """A loaded persona YAML, normalized for template use."""

    raw: dict[str, Any]
    voice: dict[str, Any] = field(default_factory=dict)
    process_domains: list[str] = field(default_factory=list)
    partner_orgs: list[str] = field(default_factory=list)
    decision_filters: list[str] = field(default_factory=list)
    # Optional grounding (P4): who supports the exec, how they work, what's confirmed.
    people: dict[str, Any] = field(default_factory=dict)
    delegates: list[dict[str, Any]] = field(default_factory=list)
    cadence: dict[str, Any] = field(default_factory=dict)
    escalation_rules: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def display_name(self) -> str:
        return self.raw["display_name"]

    @property
    def first_name(self) -> str:
        return self.display_name.split()[0]

    @property
    def title(self) -> str:
        return self.raw["title"]

    @property
    def org(self) -> str:
        return self.raw["org"]

    @property
    def charter(self) -> str:
        return self.raw.get("charter", "").strip()


def validate_persona(data: Any) -> list[str]:
    """Return a list of problems with a persona mapping; empty means valid.

    Enforces the shape the templates rely on so a sparse persona fails fast with
    a clear message instead of rendering empty sections (or crashing on a
    StrictUndefined access).
    """
    if not isinstance(data, dict):
        return ["Persona file is empty or not a YAML mapping."]

    errors: list[str] = []
    for key in ("id", "display_name", "title", "org", "charter"):
        if not str(data.get(key, "")).strip():
            errors.append(f"missing required field: {key}")

    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    if not scope.get("process_domains"):
        errors.append("scope.process_domains must list at least one domain")
    if not scope.get("partner_orgs"):
        errors.append("scope.partner_orgs must list at least one partner org")

    voice = data.get("voice_and_style") if isinstance(data.get("voice_and_style"), dict) else {}
    if not str(voice.get("tone", "")).strip():
        errors.append("voice_and_style.tone is required")
    if not voice.get("signature_phrases"):
        errors.append("voice_and_style.signature_phrases must list at least one phrase")

    if not data.get("decision_filters"):
        errors.append("decision_filters must list at least one filter")

    # Optional grounding fields (P4): validate shape only when present.
    people = data.get("people")
    if people is not None:
        if not isinstance(people, dict):
            errors.append("people must be a mapping")
        else:
            for list_key in ("direct_reports", "key_stakeholders"):
                value = people.get(list_key)
                if value is not None and not isinstance(value, list):
                    errors.append(f"people.{list_key} must be a list")

    delegates = data.get("delegates")
    if delegates is not None:
        if not isinstance(delegates, list):
            errors.append("delegates must be a list")
        else:
            for i, entry in enumerate(delegates):
                if not isinstance(entry, dict) or not str(entry.get("name", "")).strip():
                    errors.append(f"delegates[{i}] must be a mapping with a name")

    if data.get("cadence") is not None and not isinstance(data.get("cadence"), dict):
        errors.append("cadence must be a mapping")
    if data.get("escalation_rules") is not None and not isinstance(data.get("escalation_rules"), list):
        errors.append("escalation_rules must be a list")
    if data.get("provenance") is not None and not isinstance(data.get("provenance"), dict):
        errors.append("provenance must be a mapping")

    autos = data.get("automations")
    if autos is not None:
        if not isinstance(autos, list):
            errors.append("automations must be a list")
        else:
            for i, item in enumerate(autos):
                if (
                    not isinstance(item, dict)
                    or not str(item.get("name", "")).strip()
                    or not str(item.get("prompt", "")).strip()
                ):
                    errors.append(f"automations[{i}] must be a mapping with name and prompt")

    return errors


def persona_from_data(data: Any, *, source: str = "<persona>") -> Persona:
    """Validate a parsed persona mapping and flatten it for templates.

    Raises ``ValueError`` (listing every problem) if the shape is invalid.
    Kept separate from :func:`load_persona` so it can be exercised without disk.
    """
    errors = validate_persona(data)
    if errors:
        joined = "\n  - ".join(errors)
        raise ValueError(f"Persona {source} is invalid:\n  - {joined}")
    return Persona(
        raw=data,
        voice=data.get("voice_and_style", {}),
        process_domains=data.get("scope", {}).get("process_domains", []),
        partner_orgs=data.get("scope", {}).get("partner_orgs", []),
        decision_filters=data.get("decision_filters", []),
        people=data.get("people") or {},
        delegates=data.get("delegates") or [],
        cadence=data.get("cadence") or {},
        escalation_rules=data.get("escalation_rules") or [],
        provenance=data.get("provenance") or {},
    )


def load_persona(path: Path) -> Persona:
    """Parse a persona YAML file, validate its shape, and flatten it for templates."""
    return persona_from_data(yaml.safe_load(path.read_text()), source=str(path))


def render_skill(
    *,
    workflow: str,
    persona: Persona,
    slug: str,
    title: str | None = None,
) -> str:
    """Render a single workflow template into a SKILL.md string."""
    if workflow not in WORKFLOWS:
        raise ValueError(f"Unknown workflow: {workflow}")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    tpl = env.get_template(WORKFLOWS[workflow]["template"])

    skill_title = title or f"{persona.first_name}'s {WORKFLOWS[workflow]['title_suffix']}"

    people = persona.people or {}
    cadence = persona.cadence or {}
    provenance = persona.provenance or {}

    return tpl.render(
        skill_slug=slug,
        skill_title=skill_title,
        persona={
            "display_name": persona.display_name,
            "first_name": persona.first_name,
            "title": persona.title,
            "org": persona.org,
            "charter": persona.charter,
            "process_domains": persona.process_domains,
            "partner_orgs": persona.partner_orgs,
            "decision_filters": persona.decision_filters,
            "voice": {
                "tone": persona.voice.get("tone", ""),
                "framing_pattern": persona.voice.get("framing_pattern", "").strip(),
                "signature_phrases": persona.voice.get("signature_phrases", []),
                "avoid": persona.voice.get("avoid", []),
            },
            # Optional grounding — normalized so templates can test keys safely.
            "people": {
                "chief_of_staff": people.get("chief_of_staff", ""),
                "executive_assistant": people.get("executive_assistant", ""),
                "direct_reports": people.get("direct_reports", []),
                "key_stakeholders": people.get("key_stakeholders", []),
            },
            "delegates": persona.delegates,
            "cadence": {
                "timezone": cadence.get("timezone", ""),
                "working_hours": cadence.get("working_hours", ""),
                "focus_preferences": cadence.get("focus_preferences", []),
                "recurring_meetings": cadence.get("recurring_meetings", []),
            },
            "escalation_rules": persona.escalation_rules,
            "provenance": {
                "source": provenance.get("source", ""),
                "confirmed": provenance.get("confirmed", []),
                "inferred": provenance.get("inferred", []),
                "tbd": provenance.get("tbd", []),
            },
        },
    )


def validate_skill_md(
    content: str,
    *,
    expected_slug: str | None = None,
    exec_name: str | None = None,
) -> ValidationReport:
    """Validate a SKILL.md and return a :class:`ValidationReport`.

    Frontmatter spec (per the Microsoft Scout docs): the *only* required field is
    ``description`` — the skill's name is the folder name, not a frontmatter key
    (https://learn.microsoft.com/en-us/microsoft-scout/use-microsoft-scout#create-a-custom-skill).
    ``name`` is therefore optional; we still emit it (valid and portable with the
    broader Agent Skills spec) and, when present, require it to be a valid slug
    matching the folder. Pass ``expected_slug`` (the parent folder name) to check.

    Beyond the spec, this enforces the toolkit's quality bar on the body. Hard
    failures go to ``errors``; softer quality signals go to ``warnings``. Pass
    ``exec_name`` (generation time) to require the executive be named up top.
    """
    report = ValidationReport()

    if not content.startswith("---\n"):
        report.errors.append("Missing opening YAML frontmatter delimiter (---).")
        return report  # nothing else we can check

    try:
        _, fm, body = content.split("---\n", 2)
    except ValueError:
        report.errors.append("Could not find closing YAML frontmatter delimiter.")
        return report

    try:
        meta = yaml.safe_load(fm) or {}
    except yaml.YAMLError as exc:
        report.errors.append(f"Invalid YAML in frontmatter: {exc}")
        return report

    _check_frontmatter(meta, expected_slug, report)
    _check_body(body, exec_name, report)
    return report


def _check_frontmatter(
    meta: dict[str, Any], expected_slug: str | None, report: ValidationReport
) -> None:
    # description is the only frontmatter field Scout requires.
    desc = meta.get("description")
    if not desc:
        report.errors.append("Frontmatter is missing required field: description.")
    else:
        if len(desc) > MAX_DESCRIPTION_CHARS:
            report.warnings.append(
                f"Description is {len(desc)} chars; keep it under "
                f"{MAX_DESCRIPTION_CHARS} for reliable skill matching."
            )
        if len(TRIGGER_RE.findall(desc)) < MIN_TRIGGER_PHRASES:
            report.warnings.append(
                f"Description has fewer than {MIN_TRIGGER_PHRASES} quoted trigger "
                'phrases (e.g. "brief me on"); Scout matches better with more.'
            )

    # name is OPTIONAL. Validate only if present.
    name = meta.get("name")
    if name is not None:
        if not SLUG_RE.match(str(name)):
            report.errors.append(
                f"Frontmatter `name` ({name!r}) must be lowercase, hyphen-separated, "
                "3–64 chars, no leading/trailing hyphens."
            )
        elif expected_slug and name != expected_slug:
            report.errors.append(
                f"Frontmatter `name` ({name!r}) must match the skill folder "
                f"({expected_slug!r}) — Scout uses the folder name as the skill name."
            )


def _check_body(body: str, exec_name: str | None, report: ValidationReport) -> None:
    if body.strip() == "":
        report.errors.append("Body is empty — Scout needs instructions to act on.")
        return

    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        report.errors.append(f"Body exceeds {MAX_BODY_BYTES} bytes (Scout/Cowork limit).")

    lowered = body.lower()

    for phrase in FILLER_ERROR:
        if phrase in lowered:
            report.errors.append(f'Generic filler found: "{phrase}" — make it specific.')
    for phrase in FILLER_WARN:
        if phrase in lowered:
            report.warnings.append(f'Vague phrase "{phrase}" — prefer a concrete instruction.')

    checklist_items = len(CHECKBOX_RE.findall(body))
    if checklist_items < MIN_CHECKLIST_ITEMS:
        report.errors.append(
            f"Self-check has {checklist_items} checklist items; "
            f"the quality bar needs at least {MIN_CHECKLIST_ITEMS}."
        )

    if not re.search(r"(?im)^#{1,6}\s.*(quality bar|self-check)", body):
        report.warnings.append('No "Quality bar"/"self-check" heading found in the body.')

    if not any(hint in lowered for hint in SCOUT_TOOL_HINTS):
        report.warnings.append(
            "No Scout capability referenced (m365_*, WorkIQ, people search) — "
            "the skill may read as host-agnostic."
        )

    if exec_name:
        opening = " ".join(body.split()[:200]).lower()
        if exec_name.lower() not in opening:
            report.errors.append(
                f"Executive ({exec_name!r}) is not named in the first 200 words — "
                "the skill will drift into a generic assistant tone."
            )


def write_skill(
    *,
    content: str,
    slug: str,
    out_root: Path,
    overwrite: bool = False,
) -> Path:
    """Write SKILL.md to <out_root>/<slug>/SKILL.md."""
    skill_dir = out_root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    target = skill_dir / "SKILL.md"
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} already exists. Use --overwrite to replace.")
    target.write_text(content, encoding="utf-8")
    return target


def generate(
    *,
    persona_path: Path,
    workflows: list[str],
    out_root: Path,
    prefix: str | None,
    overwrite: bool,
) -> list[tuple[str, Path, ValidationReport]]:
    """Generate skills for each workflow. Returns (workflow, path, report)."""
    persona = load_persona(persona_path)
    results: list[tuple[str, Path, ValidationReport]] = []

    for wf in workflows:
        if wf not in WORKFLOWS:
            print(f"  ! Skipping unknown workflow: {wf}", file=sys.stderr)
            continue

        slug_prefix = prefix or persona.first_name.lower()
        slug = f"{slug_prefix}-{WORKFLOWS[wf]['default_slug_suffix']}"

        content = render_skill(workflow=wf, persona=persona, slug=slug)
        report = validate_skill_md(
            content, expected_slug=slug, exec_name=persona.first_name
        )
        if not report.ok:
            results.append((wf, out_root / slug / "SKILL.md", report))
            continue

        path = write_skill(
            content=content, slug=slug, out_root=out_root, overwrite=overwrite
        )
        results.append((wf, path, report))

    return results


def list_personas() -> list[Path]:
    return sorted(PERSONAS_DIR.glob("*.yaml"))


def interactive_main() -> int:
    print("Scout Compass")
    print("=" * 50)

    personas = list_personas()
    if not personas:
        print(f"No personas found in {PERSONAS_DIR}. Add one and re-run.")
        return 1

    print("\nAvailable personas:")
    for i, p in enumerate(personas, 1):
        print(f"  [{i}] {p.stem}")
    choice = input(f"\nPick a persona [1-{len(personas)}]: ").strip()
    try:
        persona_path = personas[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid choice.")
        return 1

    print("\nAvailable workflows:")
    for i, wf in enumerate(WORKFLOWS, 1):
        print(f"  [{i}] {wf} — {WORKFLOWS[wf]['title_suffix']}")
    print("  [a] all four")
    wf_choice = input(
        f"\nPick workflows (comma-separated numbers or 'a'): "
    ).strip().lower()

    if wf_choice == "a":
        workflows = list(WORKFLOWS.keys())
    else:
        wf_list = list(WORKFLOWS.keys())
        try:
            workflows = [wf_list[int(c) - 1] for c in wf_choice.split(",") if c.strip()]
        except (ValueError, IndexError):
            print("Invalid workflow choice.")
            return 1

    default_out = DEFAULT_SCOUT_SKILLS_DIR
    out_input = input(f"\nOutput directory [{default_out}]: ").strip()
    out_root = Path(out_input).expanduser() if out_input else default_out

    prefix = input(
        "Skill name prefix (e.g., 'morgan' -> 'morgan-briefing/') [default: persona first name]: "
    ).strip() or None

    overwrite_input = input("Overwrite existing SKILL.md files? [y/N]: ").strip().lower()
    overwrite = overwrite_input == "y"

    print(f"\nGenerating into {out_root} ...")
    try:
        results = generate(
            persona_path=persona_path,
            workflows=workflows,
            out_root=out_root,
            prefix=prefix,
            overwrite=overwrite,
        )
    except (ValueError, OSError) as exc:
        print(f"\nX {exc}")
        return 2

    print("\nResults:")
    for wf, path, report in results:
        if not report.ok:
            print(f"  X {wf}: validation failed")
            for e in report.errors:
                print(f"      - {e}")
        else:
            print(f"  + {wf}: {path}")
            for w in report.warnings:
                print(f"      ! {w}")

    if any(not report.ok for _, _, report in results):
        return 2
    return 0


def cli_main() -> int:
    parser = argparse.ArgumentParser(description="Microsoft Scout skill generator.")
    parser.add_argument("--persona", type=Path, help="Path to persona YAML.")
    parser.add_argument(
        "--workflows",
        default="briefing,comms,triage,strategy",
        help="Comma-separated workflow names.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_SCOUT_SKILLS_DIR,
        help=f"Output root (default: {DEFAULT_SCOUT_SKILLS_DIR}).",
    )
    parser.add_argument("--prefix", help="Skill folder/name prefix.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing SKILL.md.")
    parser.add_argument(
        "--automations-out",
        type=Path,
        help="Also export Scout automations (from the triage cadence + persona) to this directory.",
    )
    parser.add_argument(
        "--validate", type=Path, help="Validate an existing SKILL.md and exit."
    )
    args = parser.parse_args()

    if args.validate:
        try:
            content = args.validate.read_text()
        except OSError as exc:
            print(f"X cannot read {args.validate}: {exc}", file=sys.stderr)
            return 2
        # The skill name is the folder name; cross-check against it when present.
        expected_slug = args.validate.resolve().parent.name
        report = validate_skill_md(content, expected_slug=expected_slug)
        if not report.ok:
            print(f"X {args.validate} is INVALID:")
            for e in report.errors:
                print(f"   - {e}")
            for w in report.warnings:
                print(f"   ! {w}")
            return 2
        print(f"+ {args.validate} looks valid.")
        for w in report.warnings:
            print(f"   ! {w}")
        return 0

    if not args.persona:
        return interactive_main()

    workflows = [w.strip() for w in args.workflows.split(",") if w.strip()]
    try:
        results = generate(
            persona_path=args.persona,
            workflows=workflows,
            out_root=args.out.expanduser(),
            prefix=args.prefix,
            overwrite=args.overwrite,
        )
    except (ValueError, OSError) as exc:
        print(f"X {exc}", file=sys.stderr)
        return 2

    failed = False
    for wf, path, report in results:
        if not report.ok:
            failed = True
            print(f"X {wf}: validation failed")
            for e in report.errors:
                print(f"   - {e}")
        else:
            print(f"+ {wf}: {path}")
            for w in report.warnings:
                print(f"   ! {w}")

    if args.automations_out and not failed:
        try:
            persona = load_persona(args.persona)
            autos = automations.build_automations(persona, workflows, prefix=args.prefix)
        except (ValueError, OSError) as exc:
            print(f"X automation export: {exc}", file=sys.stderr)
            return 2
        if autos:
            automations.write_automations(autos, args.automations_out.expanduser())
            print(f"+ {len(autos)} automation(s) -> {args.automations_out.expanduser()}")
        else:
            print("! no automations derived (include a triage workflow or add persona 'automations')")

    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(cli_main())

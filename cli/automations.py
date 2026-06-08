"""Scout automation export.

Microsoft Scout automations are scheduled or condition-triggered tasks created in the
Automations panel — fields: Name, Prompt, Trigger type, Schedule, Condition, One-shot —
and can be imported from a GitHub repository
(https://learn.microsoft.com/en-us/microsoft-scout/use-microsoft-scout#create-automations).

The exact GitHub-import *file schema* is not publicly documented as of 2026-06. So this
module emits the documented fields through one adapter (`automation_to_doc`) and always
ships a `SETUP.md` manual path that works regardless of the importer. If you learn your
build's real schema, change `automation_to_doc` — nothing else.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:  # avoid a runtime import cycle with compass
    from compass import Persona

SCHEMA_NOTE = (
    "Field names follow Scout's documented automation fields (Name, Prompt, Trigger, "
    "Schedule, Condition, One-shot). The exact GitHub-import schema is not publicly "
    "documented as of 2026-06; if your build's importer differs, adjust automation_to_doc() "
    "in cli/automations.py. SETUP.md is the always-works manual path."
)

# Human timezone label -> IANA name, for cron scheduling.
_TZ_ALIASES = {
    "pacific": "America/Los_Angeles",
    "pt": "America/Los_Angeles",
    "eastern": "America/New_York",
    "et": "America/New_York",
    "central": "America/Chicago",
    "ct": "America/Chicago",
    "mountain": "America/Denver",
    "mt": "America/Denver",
}


def resolve_timezone(label: str) -> str:
    """Best-effort map a human tz label ('Pacific (PT) ...') to an IANA name."""
    low = (label or "").lower()
    for key, iana in _TZ_ALIASES.items():
        if re.search(rf"\b{re.escape(key)}\b", low):
            return iana
    return label or ""


@dataclass
class Automation:
    """One Scout automation, in generator-neutral form."""

    name: str
    prompt: str
    schedule_label: str = ""
    cron: str = ""
    trigger: str = "schedule"  # "schedule" | "condition"
    condition: str = ""
    one_shot: bool = False
    timezone: str = ""
    skill: str = ""  # slug of the skill this invokes (traceability)


# Triage cadence -> (label, prompt, human schedule, cron). Mirrors the triage SKILL.md presets.
_TRIAGE_PRESETS = (
    ("morning digest", "Run my morning triage digest.", "Every weekday at 6:30 AM", "30 6 * * 1-5"),
    ("end-of-day digest", "Run my end-of-day triage; emphasize tomorrow's prep.", "Every weekday at 5:30 PM", "30 17 * * 1-5"),
    ("weekly look-ahead", "Run my weekly triage.", "Every Sunday at 5:00 PM", "0 17 * * 0"),
)


def _triage_automations(first_name: str, slug: str, tz: str) -> list[Automation]:
    suffix = f" ({tz})" if tz else ""
    return [
        Automation(
            name=f"{first_name} — {label}",
            prompt=prompt,
            schedule_label=schedule + suffix,
            cron=cron,
            timezone=tz,
            skill=slug,
        )
        for label, prompt, schedule, cron in _TRIAGE_PRESETS
    ]


def _persona_automations(persona: "Persona", tz: str) -> list[Automation]:
    """Explicit automations declared in the persona YAML (optional)."""
    result: list[Automation] = []
    for item in persona.raw.get("automations") or []:
        result.append(
            Automation(
                name=item.get("name", ""),
                prompt=item.get("prompt", ""),
                schedule_label=item.get("schedule", ""),
                cron=item.get("cron", ""),
                trigger=item.get("trigger", "schedule"),
                condition=item.get("condition", ""),
                one_shot=bool(item.get("one_shot", False)),
                timezone=item.get("timezone", "") or tz,
                skill=item.get("skill", ""),
            )
        )
    return result


def build_automations(
    persona: "Persona", workflows: list[str], *, prefix: str | None = None
) -> list[Automation]:
    """Derive automations for the generated workflows, plus any persona-declared ones."""
    slug_prefix = (prefix or persona.first_name).lower()
    cadence = persona.cadence if isinstance(persona.cadence, dict) else {}
    tz = resolve_timezone(cadence.get("timezone", ""))

    automations: list[Automation] = []
    if "triage" in workflows:
        automations += _triage_automations(persona.first_name, f"{slug_prefix}-triage", tz)
    automations += _persona_automations(persona, tz)
    return automations


# --- The ADAPTER: the single place that defines the import file shape. -------
def automation_to_doc(automation: Automation) -> dict[str, Any]:
    """Map an Automation to Scout's documented automation fields.

    Generator-only extras live under ``x_generator`` (``x_*`` keys are conventionally
    ignored by importers). Change THIS function if your build's import schema differs.
    """
    return {
        "name": automation.name,
        "prompt": automation.prompt,
        "trigger": automation.trigger,
        "schedule": automation.schedule_label,
        "condition": automation.condition,
        "oneShot": automation.one_shot,
        "x_generator": {
            "cron": automation.cron,
            "timezone": automation.timezone,
            "skill": automation.skill,
        },
    }


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "automation"


# --- Pure renderers (no disk) so they can be unit-tested directly. -----------
def render_automation_yaml(automation: Automation) -> str:
    return yaml.safe_dump(automation_to_doc(automation), sort_keys=False, allow_unicode=True)


def render_manifest(automations: list[Automation]) -> str:
    manifest = {
        "version": "0.1",
        "generated_by": "scout-compass",
        "note": SCHEMA_NOTE,
        "automations": [automation_to_doc(a) for a in automations],
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False)


def render_setup_md(automations: list[Automation]) -> str:
    lines = [
        "# Scout automations — setup",
        "",
        "Two ways to add these:",
        "",
        "1. **Import** — in Scout, open **Automations** and use *import from a GitHub "
        "repository* on the folder that holds these files.",
        "2. **Manual** (always works) — open **Automations → New automation** and copy each "
        "block below.",
        "",
        f"> {SCHEMA_NOTE}",
        "",
        "First install the matching skill (its folder under `~/.copilot/skills/`); the "
        "automation's prompt is what triggers it.",
        "",
    ]
    for a in automations:
        lines += [
            f"## {a.name}",
            "",
            f"- **Prompt:** {a.prompt}",
            f"- **Trigger:** {a.trigger.capitalize()}",
        ]
        if a.trigger == "condition" and a.condition:
            lines.append(f"- **Condition:** {a.condition}")
        else:
            lines.append(f"- **Schedule:** {a.schedule_label or 'TBD'}  (cron `{a.cron or 'n/a'}`)")
        lines += [
            f"- **One-shot:** {'Yes' if a.one_shot else 'No'}",
            f"- **Invokes skill:** `{a.skill or 'n/a'}`",
            "",
        ]
    return "\n".join(lines)


def write_automations(automations: list[Automation], out_dir: Path) -> list[Path]:
    """Write per-automation YAML, a combined manifest, and a manual SETUP.md."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for automation in automations:
        path = out_dir / f"{slugify(automation.name)}.automation.yaml"
        path.write_text(render_automation_yaml(automation), encoding="utf-8")
        written.append(path)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(render_manifest(automations), encoding="utf-8")
    written.append(manifest_path)

    setup_path = out_dir / "SETUP.md"
    setup_path.write_text(render_setup_md(automations), encoding="utf-8")
    written.append(setup_path)
    return written

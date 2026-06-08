# Scout Compass — Improvement Plan

Goal: make this tool produce `SKILL.md` files that are **personal** (grounded in a real
executive's role and data) and **useful** (tied to what Microsoft Scout actually does)
for senior Microsoft executives.

Status date: 2026-06-07. Reflects the Scout docs as published at Build 2026 (2026-06-02).

---

## 1. Premise check — verified against Microsoft docs

The toolkit's foundation is correct. Confirmed against Microsoft Learn:

- Scout is a real Windows/macOS desktop agent (Frontier preview, launched 2026-06-02),
  built on the OpenClaw local-agent platform.
- Custom skills are `SKILL.md` files in folders under `~/.copilot/skills/`
  (global) or `~/.copilot/m-skills/` (synced). Bundled skills ship with the app.
- Scout auto-discovers them at the start of each conversation. No restart, no registration.

Sources:
- https://learn.microsoft.com/en-us/microsoft-scout/use-microsoft-scout
- https://learn.microsoft.com/en-us/microsoft-scout/overview

---

## 2. Correctness fix — the SKILL.md frontmatter spec (do first)

**Bug:** the toolkit treats `name` as a required frontmatter field. The official docs show
the **only required field is `description`**; the skill's *name is the folder name*. Their
example has no `name:` key at all.

Where it's wrong today:
- `cli/compass.py` → `validate_skill_md()` errors when `name` is missing.
- `README.md` → "SKILL.md spec used here" says `name` is **required** and "matches parent folder."
- `meta_skill/compass/SKILL.md` → frontmatter rules + validation checklist require `name`.

Fix:
- Require only `description`. Treat `name` as optional.
- Keep *emitting* `name` in templates (valid, and portable with the broader Agent Skills
  spec that Scout descends from), but when present, validate it matches the folder slug.
- Correct the README and meta-skill wording.

This is the highest-priority change: a spec error makes every downstream "best practice"
suspect.

---

## 3. Prioritized roadmap

Order reflects the priorities you chose: **product-accurate content → spec accuracy →
reliability**, with persona grounding last.

### P1 — Spec accuracy (Section 2) — ✅ done 2026-06-07
Bounded, mechanical, unblocks trust in everything else. Validator now requires only
`description`, treats `name` as optional, and checks the folder match when present;
README and meta-skill corrected.

### P2 — Product-accurate skill content — ✅ done 2026-06-07
The generated skills described generic research ("search Outlook"). Now tied to Scout's real
mechanisms via a shared `templates/_scout_platform.md.j2` partial plus archetype-specific
wiring (WorkIQ/`m365_*`/people search, MIP sensitivity handling, approval gates, triage
Automation + heartbeat-safe behavior, bundled `docx`/`pptx`/Web Artifacts outputs). The
meta-skill teaches all of it; examples regenerated and validated.

- **MIP sensitivity labels.** Scout elevates session sensitivity when it reads labeled
  content and refuses to write it to unprotected destinations (Teams, plain files, external
  tools). Every comms / briefing / strategy skill should instruct: check the session
  sensitivity level, never paste Confidential content into an unprotected draft, label
  before sharing. This is more useful than the abstract "compliance posture" line.
- **Name the real tools.** Replace "search Outlook/Teams/OneDrive" with **WorkIQ** for
  cross-M365 synthesis and the `m365_*` tools for direct email/calendar/Teams/OneDrive
  actions. Use Scout's **people search** for directory/org-chart resolution in "who's in
  the room."
- **Approval awareness.** Note that Scout prompts before sending email or running commands;
  comms skills should produce a draft for review, not assume auto-send.
- **Automation / Heartbeat pairing.** The triage archetype should ship with a suggested
  Automation ("Every weekday 8:00 AM") and be heartbeat-safe (heartbeat allows only generic
  outbound content and treats tentative events as busy).
- **Bundled output skills.** Offer docx / pptx / Web Artifacts Builder as output formats,
  not just markdown — e.g. a briefing can render an HTML dashboard, a strategy memo a Word doc.

Files: `templates/*.j2` (research steps, output format, compliance sections), plus matching
guidance in `meta_skill/compass/SKILL.md`.

### P3 — Reliability — ✅ done 2026-06-07
Made the quality bar real and the tool repeatable. Validator now returns a
`ValidationReport` (errors block, warnings advise) and enforces body-level rules
(≥5 checklist items, filler blocklist, ≥3 trigger phrases, exec named up top, Scout
tool referenced). Persona schema validated via `persona_from_data()` with a clear
aggregated error. CLI entry points catch persona/file errors instead of dumping
tracebacks. Added `tests/` (22 passing), `pyproject.toml`, `requirements.txt`, `.gitignore`.

- **Body-level validation.** The validator only checks frontmatter. Enforce the rules the
  README already claims: exec named in the first ~200 words, ≥3 literal trigger phrases in
  the description, ≥1 named KPI, a compliance/sensitivity touchpoint, ≥5 self-check items,
  and a filler-word blocklist ("be helpful", "as needed", "do your best").
- **Errors vs. warnings.** Split the validator return so spec violations fail but style
  issues (e.g. long description) warn. Update `web/app.py` and `generate()` accordingly.
- **Persona schema validation.** Validate persona YAML shape with clear messages instead of
  letting StrictUndefined crash mid-render.
- **Tests + packaging.** A small `pytest` suite (validator rules, slug rules, render-all +
  validate round trip) and a `pyproject.toml` / `requirements.txt` for repeatable installs.

### P4 — Deeper persona grounding — ✅ done 2026-06-07
Persona schema gained optional grounding fields — `people` (chief of staff, EA, direct
reports, key stakeholders), `delegates`, `cadence` (time zone, working hours, focus,
recurring meetings), `escalation_rules`, and `provenance` (source + confirmed/inferred/tbd).
A shared `templates/_persona_grounding.md.j2` partial renders these in every archetype, with
an M365 people-search **enrichment fallback** when fields are blank. The seed Morgan persona
leaves private people blank (no fabricated names) and marks inferred vs. TBD via provenance;
the meta-skill teaches the enrichment + provenance discipline. Validator type-checks the new
fields when present; 5 new tests cover enriched + fallback rendering.

### Automation export (beyond P4) — ✅ done 2026-06-07
`cli/automations.py` derives Scout automations from the triage cadence (+ optional persona
`automations:`) and exports them: per-automation YAML, a combined `manifest.json`, and a
manual `SETUP.md`. Wired into the CLI (`--automations-out`) and the web download zip.
**Honesty note:** Scout's automations feature and GitHub import are documented, but the
exact import *file schema* is not public as of 2026-06 — so the field mapping lives in one
adapter (`automation_to_doc`) and SETUP.md is the always-works manual path. Verify against
your Frontier build and adjust the adapter if needed.

---

## 4. Triage of the brainstorm notes

Folding in the longer brainstorm. Adopted where it fits Scout's real model; corrected where
it doesn't.

| Idea | Verdict | Note |
|------|---------|------|
| NL "skill builder" / intent capture | Adopt | Already the meta-skill's job; strengthen its intake. |
| Use-case templates for execs | Adopt — done | Now 8 archetypes; added meeting-prep, decisions-log, 1:1 prep, and review prep. |
| Proactive/contextual suggestions | Adopt → map to Scout | Implement as Automations + Heartbeat, not a custom UI. |
| Executive persona config (stakeholders, recurring reports, comms style) | Adopt | This is P4 persona-schema work. |
| Categorization / tagging / versioning / sharing | Partial | Versioning = git + `m-skills` sync. Tagging is low value for file-based skills. |
| **"Scout is internal Microsoft tooling"** | Correct | It's a public Frontier-preview desktop app on OpenClaw, not internal tooling. |
| **"Skills files are JSON/YAML"** | Correct | They are `SKILL.md` — Markdown body + YAML frontmatter; only `description` required. |
| **"Register/update skills via a Scout API or CLI"** | Correct | No skills API. Installation = drop a folder in `~/.copilot/skills/`; auto-discovered. |
| **"Skills have a Parameters/Arguments block + execution logic"** | Correct | Skills are prompt-style instructions. Scout elicits parameters at runtime by asking; it executes via its own tools (filesystem, shell, browser, `m365_*`, WorkIQ). |
| **Splitting one ask into hyper-specific one-shot skills** (`summarize_ai_team_discussion`) | Reframe | A reusable skill should be archetype-level ("meeting prep"), not a single-use function. |
| Usage analytics | Defer | Scout exposes no skill-usage telemetry to a file-based tool. |
| React/Angular + Postgres/Mongo + Docker/K8s + OAuth backend | Reject (scope) | The artifact is a text file in a folder. The current CLI + optional Flask preview is correctly scoped; a service stack adds cost without changing the output. |

---

## 5. Non-goals

- No database, no Kubernetes, no custom skills-registration service. The deliverable is a
  validated `SKILL.md` in a folder.
- No fabricated KPIs, quotes, or signature phrases in generated skills (already enforced in
  the templates; keep it).

---

## 6. Open questions

1. Which executives beyond Morgan should be seeded? (Each needs a sourced persona YAML.)
2. Default output tier — global (`~/.copilot/skills/`) or synced (`~/.copilot/m-skills/`)?
3. Are docx / pptx / HTML outputs wanted now, or keep skills markdown-only for v1?

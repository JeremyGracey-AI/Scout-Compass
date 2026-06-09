# Scout Compass

> Navigate from idea to installed skill with a smooth build, preview, and install flow.

A toolkit for authoring **Microsoft Scout** `SKILL.md` files tuned to senior Microsoft executives.

It ships three ways to create skills:

1. **Python CLI** (`cli/compass.py`) — interactive or scriptable; writes directly into `~/.copilot/skills/`.
2. **Web app** (`web/app.py`) — a persona-builder UI for non-technical users: fill a form (no YAML), preview the skills + automations, then one-click install into the Scout skills folder (or download a `.zip`). See [Web app](#web-app).
3. **Meta-skill** (`meta_skill/compass/SKILL.md`) — drop this into Scout itself so Scout can author new exec skills on demand.

All three share the same eight executive workflow archetypes:

| Archetype | What the resulting skill produces |
|-----------|-----------------------------------|
| `briefing` | One-page exec brief with KPI table, partner-org list, talking points |
| `comms` | Audience-mode draft (team / partner-org / CVP / external / quick-reply / all-hands) with 3 subject lines and risk flags |
| `triage` | Daily or weekly digest: top-of-mind (≤5), compliance flags, KPI exceptions, calendar table, delegations |
| `strategy` | 2–4 page memo with recommendation, options table, sequencing, open questions |
| `meeting-prep` | Run-of-show pack for a specific meeting: objective, time-boxed agenda, attendees + decision power, decisions to land, talking points |
| `decisions-log` | Durable decision record: the call, options weighed, owner/approver, compliance + KPI tie, follow-ups, review date |
| `one-on-one` | 1:1 prep card: since-last-time, follow-ups owed both ways, decisions to align, one earned growth/recognition note |
| `review-prep` | MBR/QBR pack: KPI scorecard vs. target, narrative, wins, risks with recovery owners, asks for the room |

## Seeded persona

The repo ships with one persona — **Morgan Reyes**, General Manager, Operations Enablement (Business Operations) — assembled from his [public LinkedIn profile](https://www.linkedin.com/in/morganreyes). Charter, process domains, partner orgs, signature phrasing, and decision filters are all sourced.

Add more personas by dropping new YAML files into `personas/` matching the same shape.

## Quickstart

```bash
pip install pyyaml jinja2 flask

# CLI — generate the four core skills for Morgan
python cli/compass.py \
  --persona personas/morgan_reyes.yaml \
  --workflows briefing,comms,triage,strategy \
  --out ~/.copilot/skills \
  --prefix morgan

# CLI — interactive mode
python cli/compass.py

# Web UI
python web/app.py
# open http://127.0.0.1:5000
```

## Installing the generated skills into Scout

Scout discovers custom skills automatically. Just place each skill folder in one of these directories
([Microsoft docs](https://learn.microsoft.com/en-us/microsoft-scout/use-microsoft-scout#create-a-custom-skill)):

| Tier | Path | When to use |
|------|------|-------------|
| Global user | `~/.copilot/skills/<slug>/SKILL.md` | This machine, all conversations |
| Workspace (synced) | `~/.copilot/m-skills/<slug>/SKILL.md` | Synced across your devices |

No restart needed — Scout picks them up at the start of the next conversation.

## Installing the meta-skill

```bash
cp -r meta_skill/compass ~/.copilot/skills/
```

Then ask Scout: *"Make a new comms skill for Morgan Reyes — he needs help drafting board-up updates on the partner lifecycle KPIs."* The meta-skill walks Scout through gathering the right persona context and producing a validated SKILL.md.

## Repo layout

```
scout-compass/
├── cli/
│   └── compass.py              # generator + validator + interactive CLI
├── web/
│   ├── app.py                  # Flask app
│   └── templates/index.html    # single-page UI
├── meta_skill/
│   └── compass/
│       └── SKILL.md            # the skill that teaches Scout to author exec skills
├── personas/
│   └── morgan_reyes.yaml      # seed persona
├── templates/
│   ├── briefing.md.j2          # Jinja2 templates — one per archetype
│   ├── comms.md.j2
│   ├── triage.md.j2
│   ├── strategy.md.j2
│   ├── meeting-prep.md.j2
│   ├── decisions-log.md.j2
│   ├── one-on-one.md.j2
│   └── review-prep.md.j2
├── examples/
│   └── morgan/                   # snapshot of generated skills for reference
└── README.md
```

## SKILL.md spec used here

Per the [Microsoft Scout docs](https://learn.microsoft.com/en-us/microsoft-scout/use-microsoft-scout#create-a-custom-skill):

- The **skill name is the folder name** (e.g. `morgan-briefing/`), lowercase-hyphen.
- YAML frontmatter delimited by `---`. The **only required field is `description`** (what the skill does + when to use it). The generator also emits an explicit `name` for portability with the broader Agent Skills spec and validates that it matches the folder — but Scout itself does not require it.
- Markdown body with the skill instructions. Up to ~1 MB. Keep it lean — Scout loads the whole body when the skill activates.
- Drop the folder into `~/.copilot/skills/<slug>/` (or `~/.copilot/m-skills/<slug>/` to sync across devices). Auto-discovered at the start of each conversation.

The generator's validator (`--validate <path>`) enforces these rules.

## Design choices worth knowing

- **Every generated skill names the exec by first name throughout.** Generic "the user" wording is the #1 tell of a low-effort skill — Scout loses persona grounding the moment it slips.
- **Compliance posture is required, even if "no material exposure."** Microsoft execs operate under SOX and adjacent controls; ignoring compliance is the second-biggest tell.
- **Partner orgs are listed by name.** Microsoft work is cross-functional — Sales, Finance, Engineering, Legal, Risk, Partner Program, Operations, Engineering. Skills that say "the team" instead activate weakly.
- **Self-check checklists in every skill.** Each generated SKILL.md ends with a checklist the skill runs against its own output before delivering. This is the single highest-leverage quality lever.
- **No fabricated KPIs or quotes.** The templates explicitly forbid invented numbers and require inline citations.

## Adding a new executive

1. Copy `personas/morgan_reyes.yaml` to `personas/<new>.yaml`.
2. Fill in: `id`, `display_name`, `title`, `org`, `charter`, `scope.process_domains`, `scope.partner_orgs`, `voice_and_style`, `decision_filters`.
3. Run the generator. No template changes needed.

Prefer not to touch YAML? Build the executive in the web app and click **Export .yaml** to
download a ready-to-commit `personas/<id>.yaml` — then drop it in `personas/` and commit.

## Web app

A browser app aimed at non-technical users — build an executive, preview, and install,
without touching YAML.

```bash
pip install -e ".[web]"   # or: pip install -r requirements.txt
python web/app.py         # open http://127.0.0.1:5000
```

What it does:

- **Persona builder** — a plain-language form (name, title, org, charter, KPIs, partners,
  voice, plus optional support team / cadence / escalation). The server renders skills from
  the same Python templates the CLI uses, so output is identical.
- **Skill picker & catalog** — choose which of the eight archetypes to generate from grouped,
  described cards (each with example triggers and a *recurring* badge), with one-click presets
  ("Daily driver," "Leadership review," …), Select all / Clear, and a *Browse archetypes*
  catalog that explains the whole menu.
- **Live preview** — each skill with its validation errors/warnings, plus the derived
  automations.
- **One-click install** — uses the browser **File System Access API** to write
  `<slug>/SKILL.md` (and `automations/`) straight into the Scout skills folder you pick. The
  server never touches your local files.
- **Manage installed skills** — browse the skills already in that folder, grouped by
  executive, each showing its description and a live validation status (valid / warnings /
  errors); preview a `SKILL.md` in place, or remove it.
- **Zip fallback** — browsers without the File System Access API (Safari, Firefox) get a
  `.zip` to unzip into `~/.copilot/skills/`.
- **Export persona** — download what you built as a ready-to-commit `personas/<id>.yaml`
  (the same schema the CLI reads), so a browser-built executive can be seeded into the repo
  without hand-writing YAML.

### Accounts & persona library (Phase 2)

Signed-in users get a saved **persona library** — Supabase Postgres + email magic-link auth,
with row-level security so each library is private to its owner. Generation stays server-side
and **no-store**; the library is handled browser↔Supabase directly, so the Flask server holds
no user data or secrets. Enable it by setting `SUPABASE_URL` / `SUPABASE_ANON_KEY` (see
`web/.env.example`); leave them unset and the app runs library-free.

Hosting (Vercel) and the later **Azure + Entra ID** migration path are in
**[DEPLOY.md](DEPLOY.md)**. Still unverified: the **Scout automation import file schema** —
`cli/automations.py`'s `automation_to_doc` is the one place to change once confirmed.

## Development

```bash
# Install (editable) with dev + web extras
pip install -e ".[dev,web]"      # or: pip install -r requirements.txt

# Run the test suite
pytest
```

The validator distinguishes **errors** (block generation / fail `--validate`) from
**warnings** (surfaced, non-blocking). Beyond the frontmatter spec it enforces the
quality bar on the body: the executive is named in the first 200 words, the
description carries enough trigger phrases, the self-check has ≥ 5 items, a real Scout
capability is referenced, and there's no generic filler. Persona YAML is schema-checked
on load, so a sparse persona fails fast with a clear message instead of rendering empty
sections.

## License

Internal use. Adapt freely.

"""Load and validate the registry, target specs, and machine profiles.

Validation fails loudly: unknown audiences, bad project stages, missing partials, and
dangling references are errors, not warnings. Schema validation is the first test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

KNOWN_TARGETS = {"hermes", "claude-code", "antigravity", "agents-md", "claude-app"}
VALID_STAGES = {"ideation", "speccing", "build", "maintain"}
VALID_SKILL_SCOPES = {"global", "project"}
# Targets with a project-scoped skill deploy path (claude-code: <local_path>/.claude/skills/,
# antigravity: <local_path>/.agents/skills/) — the only targets a project's `skills:` list
# binds a skill for, and the only targets where `scope: project` changes anything. hermes and
# claude-app have no project-scoped surface at all (account-wide/global only) and simply
# IGNORE `scope` — always global, on any skill, regardless of value — the same way hermes
# always did before this feature existed. See validate_skill_scope / Skill.scope.
PROJECT_SCOPE_CAPABLE_TARGETS = {"claude-code", "antigravity"}

# The user-identity config (registry/user.yaml + registry/local/user.yaml overlay):
# the single source of truth for the personalization placeholders render.py expands
# ({{user_given_name}}, {{users_given_name}}, {{user_full_name}}, {{user_email}},
# {{user_location}}). A fixed, closed schema — unknown keys are rejected loudly rather
# than silently ignored, the same posture as every other registry file.
KNOWN_USER_KEYS = {"given_name", "full_name", "email", "location"}
_DEFAULT_USER = {"given_name": "User", "full_name": "Mitos User",
                 "email": "user@example.com", "location": "Your City, State"}

# The structural anchor a skill extension splices under (render-time only — see
# render.compose_skill_body). Fixed and order-independent: extensions land as new
# subsections at the end of this section, never matched against a specific existing
# role heading, so a role rename never orphans an extension (the R2 design decision).
EXTENSION_ANCHOR = "## Extended C-suite Roles"

# Supporting-file subdirectories a skill folder may carry alongside SKILL.md —
# auto-deployed next to the rendered SKILL.md and bundled into claude-app zips.
# The set is the union of the harnesses' documented conventions: examples/ + scripts/
# (Claude Code, Antigravity), references/ + templates/ (Hermes), resources/
# (Antigravity). A whitelist rather than "any file" — it keeps the console's
# Supporting Files panel and adopt routing over a known, enumerable surface.
_SKILL_RESOURCE_DIRS = ("examples", "scripts", "references", "templates", "resources")

# Mitos overlay (the Mitos overlay design): registry/local/ is the gitignored personal
# overlay — the public core ships neutral defaults, a user's identity/projects/graph/skills
# live here, untracked. Loaded after the core with last-layer-wins precedence.
LOCAL_OVERLAY = "local"


def inbox_dir(reg, root: Path | None = None) -> Path:
    """The private intake queue — always under registry/local/ so it syncs with the
    mitos-local overlay repo and never touches the public-track repo. `root` is the
    sandbox base when running under `--root <dir>`; omit for the real repo."""
    base = root if root is not None else reg.root
    return base / "registry" / LOCAL_OVERLAY / "inbox"


_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


class RegistryError(Exception):
    """Schema or reference error in the registry. Aborts compilation."""


def _repo_basename(repo: str) -> str:
    """The checkout directory name for a git URL: the last path segment, minus `.git`.
    Handles scp-style (`git@host:owner/name.git`) and URL (`https://…/name.git`) forms."""
    s = repo.strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    return s.replace(":", "/").rsplit("/", 1)[-1] or "repo"


def resolve_local_path(machine_name: str, machine: dict, raw: str) -> str:
    """Resolve a project's `local_path` entry for one machine.

    Absolute values pass through: `~`-rooted, `/`-rooted, or drive-lettered (`D:/…`).
    Relative values (just a dir name) resolve against the machine's `projects_root`
    path key — that's where per-PC differences live (one Windows box keeps projects
    on C:\\, another on D:\\), so manifests stay drive-agnostic.
    """
    s = str(raw).replace("\\", "/").strip()
    if s.startswith(("~", "/")) or (len(s) >= 2 and s[1] == ":"):
        return s
    root = (machine.get("paths") or {}).get("projects_root")
    if not root:
        raise RegistryError(
            f"machine {machine_name}: relative local_path {raw!r} requires a "
            f"'projects_root' under paths: in machines/{machine_name}.yaml")
    return f"{str(root).rstrip('/')}/{s}"


@dataclass
class Partial:
    rel: str                       # e.g. "identity/security.md" (registry-relative)
    audience: list[str] | None     # None == all targets
    body: str

    def visible_to(self, target: str) -> bool:
        return self.audience is None or target in self.audience


@dataclass
class SkillResource:
    """One supporting file under a skill's resource subdirectories (_SKILL_RESOURCE_DIRS).
    `rel` is its OWN registry-relative path (not SKILL.md's) — so adopt/harvest routes
    an edited script back to the file that authored it (see planner._skill_resource_outputs)."""
    text: str
    rel: str


@dataclass
class Skill:
    name: str
    rel: str                       # registry-relative path to SKILL.md
    frontmatter: dict
    body: str
    # supporting files (examples/, scripts/), keyed by their path relative to the skill
    # folder (e.g. "examples/sample.md", "scripts/validate.sh")
    resources: dict[str, SkillResource] = field(default_factory=dict)

    @property
    def targets(self) -> list[str]:
        return self.frontmatter.get("targets", [])

    @property
    def category(self) -> str:
        return self.frontmatter.get("category", "general")

    @property
    def scope(self) -> str:
        """`global` (default): deploys to every global surface a target offers
        (hermes, the antigravity_skills dir, claude-app zips). `project`: deploys ONLY
        into the project checkouts that bind it via that project's `skills:` list —
        never a global directory. Hermes deliberately ignores this field (it has no
        project-scoped skill surface); see validate_skill_scope."""
        return self.frontmatter.get("scope", "global")


@dataclass
class Agent:
    """A Claude Code subagent, authored once in registry/agents/<name>.md and bound to
    projects via the manifest. Harness-agnostic source; today only a claude-code flavor
    emits it (the agents design)."""
    name: str
    rel: str                       # registry-relative path to <name>.md
    frontmatter: dict
    body: str


@dataclass
class Prompt:
    """A harness-agnostic reusable prompt, authored in registry/prompts/<name>.md.
    The substrate every harness understands. Skills and agents are progressive enhancement
    on top; a Prompt degrades gracefully to copy-paste where no native deployment path
    exists. `targets:` is optional — omitting it means console-only (not an error)."""
    name: str
    rel: str                       # registry-relative path to <name>.md
    frontmatter: dict
    body: str

    @property
    def targets(self) -> list[str]:
        return self.frontmatter.get("targets", [])

    @property
    def category(self) -> str:
        return self.frontmatter.get("category", "general")


@dataclass
class Registry:
    root: Path                     # repo root
    partials: dict[str, Partial]   # keyed by registry-relative path
    skills: dict[str, Skill]       # keyed by skill name
    servers: dict                  # servers.yaml -> {"servers": {...}}
    projects: dict[str, dict]      # keyed by slug
    targets: dict[str, dict]       # keyed by target name
    machines: dict[str, dict]      # keyed by machine name
    graphs: dict = field(default_factory=dict)   # slug -> graph.ProjectGraph (lazy;
                                   # empty unless registry/graph/ holds JSON-LD files)
    agents: dict = field(default_factory=dict)   # name -> Agent (registry/agents/)
    prompts: dict = field(default_factory=dict)  # name -> Prompt (registry/prompts/)
    user: dict = field(default_factory=lambda: dict(_DEFAULT_USER))  # given_name,
                                   # full_name, email, location — core defaults merged
                                   # with registry/local/user.yaml (field-level overlay)

    def partial(self, rel: str) -> Partial:
        if rel not in self.partials:
            raise RegistryError(f"reference to unknown partial: {rel}")
        return self.partials[rel]


def _split_frontmatter(text: str, where: str) -> tuple[dict, str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text  # no frontmatter is allowed for plain bodies
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise RegistryError(f"invalid frontmatter in {where}: {e}") from e
    if not isinstance(meta, dict):
        raise RegistryError(f"frontmatter in {where} must be a mapping")
    return meta, m.group(2)


def _load_user(dir_path: Path, label: str) -> dict:
    """One layer of user.yaml (core or overlay) — {} when the file is absent, so a
    hermetic test registry without one still loads fine (the dataclass default supplies
    neutral values). Unlike `_load_yaml`, an empty file is valid (yaml.safe_load returns
    None) rather than a schema error, since a scaffolded overlay may start blank."""
    path = dir_path / "user.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{label}: must be a YAML mapping")
    bad = set(data) - KNOWN_USER_KEYS
    if bad:
        raise RegistryError(f"{label}: unknown key(s) {sorted(bad)} — known: "
                            f"{sorted(KNOWN_USER_KEYS)}")
    for k, v in data.items():
        if not isinstance(v, str):
            raise RegistryError(f"{label}: {k!r} must be a string")
    return data


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{path} must be a YAML mapping")
    return data


def load(root: Path, ignore_local: bool = False) -> Registry:
    reg_dir = root / "registry"
    if not reg_dir.is_dir():
        raise RegistryError(f"no registry/ directory at {root}")

    partials = _load_partials(reg_dir)
    skills = _load_skills(reg_dir)
    agents = _load_agents(reg_dir)
    prompts = _load_prompts(reg_dir)
    projects = _load_projects(reg_dir)
    graphs = _load_graphs(reg_dir)
    user = {**_DEFAULT_USER, **_load_user(reg_dir, "registry/user.yaml")}

    # Mitos overlay (the Mitos overlay design): load registry/local/ on top of the core with
    # last-layer-wins precedence — a local entry replaces a same-key core entry, new local
    # keys are added, core-only keys remain. Absent overlay (the public default) is identical
    # to core-only, so this is purely additive. Overlay entries carry a `local/` rel prefix so
    # their real file location (and adopt routing) point back into registry/local/.
    local_dir = reg_dir / LOCAL_OVERLAY
    if local_dir.is_dir() and not ignore_local:
        pfx = f"{LOCAL_OVERLAY}/"
        partials = _overlay(partials, _load_partials(local_dir, prefix=pfx))
        skills = _overlay(skills, _load_skills(local_dir, prefix=pfx))
        agents = _overlay(agents, _load_agents(local_dir, prefix=pfx))
        prompts = _overlay(prompts, _load_prompts(local_dir, prefix=pfx))
        local_projects = _load_projects(local_dir, is_local=True)
        projects = _overlay(projects, local_projects)
        graphs = _overlay(graphs, _load_graphs(local_dir))
        user = {**user, **_load_user(local_dir, "registry/local/user.yaml")}

    # MCP servers are moat TOOLS, not registry content — they live in connections/
    # (own deploy lane); see the connections-lane design.
    conn = root / "connections" / "servers.yaml"
    if not conn.is_file():
        raise RegistryError(f"missing {conn} — MCP servers live in connections/")
    servers = _load_yaml(conn)
    targets = _load_dir_of_yaml(root / "targets", key="target")
    machines = _load_dir_of_yaml(root / "machines", key="name")

    # Mitos overlay for machines and connections: same last-layer-wins contract as
    # partials/skills/projects. Private machine profiles with real hostnames/IPs and
    # server configs with LAN addresses live in registry/local/ (gitignored).
    if local_dir.is_dir() and not ignore_local:
        local_machines_dir = local_dir / "machines"
        if local_machines_dir.is_dir() and any(local_machines_dir.glob("*.yaml")):
            machines = _overlay(machines, _load_dir_of_yaml(local_machines_dir, key="name"))
        local_conn = local_dir / "connections" / "servers.yaml"
        if local_conn.is_file():
            local_servers = _load_yaml(local_conn)
            # Field-level deep merge: overlay entries update individual fields (e.g. url:)
            # without clobbering the core's graph_enum, tools, etc. New servers are added;
            # core-only servers remain.
            core_s = servers.get("servers") or {}
            local_s = local_servers.get("servers") or {}
            merged: dict = {**core_s}
            for sname, sval in local_s.items():
                if sname in merged and isinstance(merged[sname], dict) and isinstance(sval, dict):
                    merged[sname] = {**merged[sname], **sval}
                else:
                    merged[sname] = sval
            servers["servers"] = merged

    reg = Registry(root=root, partials=partials, skills=skills, servers=servers,
                   projects=projects, targets=targets, machines=machines, graphs=graphs,
                   agents=agents, prompts=prompts, user=user)
    _validate(reg)
    return reg


def _overlay(core: dict, local: dict) -> dict:
    """Last-layer-wins merge for the Mitos overlay (the Mitos overlay design): a local entry
    replaces a same-key core entry, new local keys are added, core-only keys remain. A
    documented contract, never an ad-hoc merge — so loads stay deterministic and reproducible."""
    merged = dict(core)
    merged.update(local)
    return merged


def _load_partials(base: Path, *, prefix: str = "") -> dict[str, Partial]:
    out: dict[str, Partial] = {}
    for sub in ("identity", "context"):
        d = base / sub
        if not d.is_dir():
            continue
        for md in d.rglob("*.md"):
            logical = md.relative_to(base).as_posix()     # dict key = the override identity
            meta, body = _split_frontmatter(md.read_text(encoding="utf-8"), prefix + logical)
            audience = meta.get("audience")
            if audience is not None and not isinstance(audience, list):
                raise RegistryError(f"{prefix + logical}: 'audience' must be a list")
            out[logical] = Partial(rel=prefix + logical, audience=audience,
                                   body=body.strip("\n"))
    return out


def _load_skill_resources(skill_dir: Path, base: Path, prefix: str,
                          rel: str) -> dict[str, SkillResource]:
    """Supporting files under a skill's resource subdirectories (_SKILL_RESOURCE_DIRS), keyed by
    path relative to the skill folder. v1 is text-only — a binary asset fails loudly
    (no silent truncation/corruption) rather than being supported half-way."""
    resources: dict[str, SkillResource] = {}
    for sub in _SKILL_RESOURCE_DIRS:
        subdir = skill_dir / sub
        if not subdir.is_dir():
            continue
        for f in sorted(subdir.rglob("*")):
            if not f.is_file():
                continue
            relpath = f.relative_to(skill_dir).as_posix()
            resource_rel = prefix + f.relative_to(base).as_posix()
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                raise RegistryError(
                    f"{resource_rel}: skill resource files must be UTF-8 text — "
                    f"binary assets are not supported (v1 constraint)") from e
            resources[relpath] = SkillResource(text=text, rel=resource_rel)
    return resources


def _load_skills(base: Path, *, prefix: str = "") -> dict[str, Skill]:
    out: dict[str, Skill] = {}
    sdir = base / "skills"
    if not sdir.is_dir():
        return out
    for sk in sdir.glob("*/SKILL.md"):
        rel = prefix + sk.relative_to(base).as_posix()
        meta, body = _split_frontmatter(sk.read_text(encoding="utf-8"), rel)
        name = meta.get("name")
        if not name:
            raise RegistryError(f"{rel}: skill missing 'name'")
        if name in out:
            raise RegistryError(f"{rel}: duplicate skill name {name!r} "
                                f"(also declared by {out[name].rel})")
        resources = _load_skill_resources(sk.parent, base, prefix, rel)
        out[name] = Skill(name=name, rel=rel, frontmatter=meta, body=body.strip("\n"),
                          resources=resources)
    return out


def _load_agents(base: Path, *, prefix: str = "") -> dict[str, Agent]:
    out: dict[str, Agent] = {}
    adir = base / "agents"
    if not adir.is_dir():
        return out
    for af in sorted(adir.glob("*.md")):
        rel = prefix + af.relative_to(base).as_posix()
        meta, body = _split_frontmatter(af.read_text(encoding="utf-8"), rel)
        name = meta.get("name")
        if not name:
            raise RegistryError(f"{rel}: agent missing 'name'")
        if name in out:
            raise RegistryError(f"{rel}: duplicate agent name {name!r} "
                                f"(also declared by {out[name].rel})")
        if not meta.get("description"):
            raise RegistryError(f"{rel}: agent {name!r} missing 'description'")
        out[name] = Agent(name=name, rel=rel, frontmatter=meta, body=body.strip("\n"))
    return out


def _load_prompts(base: Path, *, prefix: str = "") -> dict[str, Prompt]:
    out: dict[str, Prompt] = {}
    pdir = base / "prompts"
    if not pdir.is_dir():
        return out
    for pf in sorted(pdir.glob("*.md")):
        rel = prefix + pf.relative_to(base).as_posix()
        meta, body = _split_frontmatter(pf.read_text(encoding="utf-8"), rel)
        name = meta.get("name")
        if not name:
            raise RegistryError(f"{rel}: prompt missing 'name'")
        if name in out:
            raise RegistryError(f"{rel}: duplicate prompt name {name!r} "
                                f"(also declared by {out[name].rel})")
        out[name] = Prompt(name=name, rel=rel, frontmatter=meta, body=body.strip("\n"))
    return out


def _load_projects(base: Path, *, is_local: bool = False) -> dict[str, dict]:
    out: dict[str, dict] = {}
    pdir = base / "projects"
    if not pdir.is_dir():
        return out
    for py in pdir.glob("*.yaml"):
        data = _load_yaml(py)
        slug = data.get("slug")
        if not slug:
            raise RegistryError(f"{py.name}: project missing 'slug'")
        if slug in out:
            raise RegistryError(f"{py.name}: duplicate project slug {slug!r}")
        # A leftover `org:` field is rejected in _validate() — org domains are tagged
        # per knowledge-graph effort (see known_org_domains()), never on the manifest.
        # `_is_local` tags a manifest loaded from the registry/local/ overlay so accepted
        # content (notably knowledge graphs) routes back into the overlay, never the core
        # — the loader reads local graphs only from registry/local/graph/ when the overlay
        # supplies projects, so a core write would be silently ignored.
        data["_is_local"] = is_local
        out[slug] = data
    return out


def _load_graphs(base: Path) -> dict:
    """Load + validate every project knowledge graph under <base>/graph/.

    Returns {} (without importing rdflib) when the directory is absent or empty, so the
    graph dependency only bites where graph content actually exists. A GraphError is
    rewrapped as a RegistryError — a malformed graph aborts compilation loudly, exactly
    like a dangling partial.
    """
    gdir = base / "graph"
    if not gdir.is_dir():
        return {}
    files = sorted(gdir.glob("*.jsonld"))
    if not files:
        return {}
    from . import graph as graphmod
    out: dict = {}
    for jf in files:
        try:
            pg = graphmod.load_project_graph(jf)
        except graphmod.GraphError as e:
            raise RegistryError(str(e)) from e
        if pg.slug in out:
            raise RegistryError(f"graph {jf.name}: duplicate project slug {pg.slug!r}")
        out[pg.slug] = pg
    return out


def _load_dir_of_yaml(folder: Path, *, key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not folder.is_dir():
        raise RegistryError(f"missing directory: {folder}")
    for yf in folder.glob("*.yaml"):
        data = _load_yaml(yf)
        name = data.get(key)
        if not name:
            raise RegistryError(f"{yf.name}: missing '{key}'")
        if name in out:
            # two files claiming one identity would silently shadow each other
            # (glob order decides the winner) — refuse loudly instead
            raise RegistryError(f"{yf.name}: duplicate {key} {name!r} — another file "
                                f"in {folder.name}/ already declares it")
        out[name] = data
    return out


def known_org_domains(reg: Registry) -> set[str]:
    """The valid org-domain tags for a knowledge-graph effort: every domain declared by
    a skill's `org_domain` frontmatter key (core + overlay, already merged on `reg`) —
    the console's `+ ORG` button adds a domain purely by proposing a new skill candidate
    with this key, no loader change required. Falls back to the legacy hardcoded set
    when no skill declares one yet, so a repo mid-migration doesn't suddenly invalidate
    every effort tagged software/design/marketing."""
    declared = {s.frontmatter.get("org_domain") for s in reg.skills.values()
               if s.frontmatter.get("org_domain")}
    return declared or {"software", "design", "marketing"}


def validate_skill_extension(reg: "Registry", skill_name: str, frontmatter: dict) -> str | None:
    """Cross-check an `extends_skill`/`extends_role` pair declared on `skill_name`'s
    frontmatter. Returns an error string, or None when the pair is absent (not an
    extension) or valid. Shared by `_validate` (compile-time) and the console's
    propose/accept path (review._revalidate_verbatim, propose_meta_edit,
    propose_new_skill) so a bad console edit is caught before it ever reaches the
    registry — see R1/R2 in the extensions design."""
    ext_skill = frontmatter.get("extends_skill")
    ext_role = frontmatter.get("extends_role")
    if not ext_skill and not ext_role:
        return None
    if bool(ext_skill) != bool(ext_role):
        return (f"skill {skill_name!r}: 'extends_skill' and 'extends_role' must be "
                f"specified together")
    if ext_skill == skill_name:
        return f"skill {skill_name!r}: cannot extend itself"
    parent = reg.skills.get(ext_skill)
    if parent is None:
        return f"skill {skill_name!r}: extends_skill {ext_skill!r} is not a known skill"
    if parent.frontmatter.get("extends_skill"):
        return (f"skill {skill_name!r}: cannot extend {ext_skill!r} — it is itself an "
                f"extension (chained extensions are not supported)")
    if EXTENSION_ANCHOR not in parent.body:
        return (f"skill {skill_name!r}: parent skill {ext_skill!r} has no "
                f"{EXTENSION_ANCHOR!r} section to extend")
    return None


def validate_skill_scope(skill_name: str, frontmatter: dict) -> str | None:
    """Cross-check a skill's `scope` frontmatter key. Returns an error string, or None
    when valid. No per-target incompatibility to check: a target with no project-scoped
    surface (hermes, claude-app) simply ignores `scope` and always deploys globally, so
    `scope: project` is always a legal value regardless of which targets a skill declares
    — see PROJECT_SCOPE_CAPABLE_TARGETS."""
    scope = frontmatter.get("scope", "global")
    if scope not in VALID_SKILL_SCOPES:
        return (f"skill {skill_name!r}: invalid scope {scope!r}; must be one of "
                f"{sorted(VALID_SKILL_SCOPES)}")
    return None


def _validate(reg: Registry) -> None:
    # audiences reference known targets
    for p in reg.partials.values():
        if p.audience:
            bad = set(p.audience) - KNOWN_TARGETS
            if bad:
                raise RegistryError(f"{p.rel}: unknown audience(s) {sorted(bad)}")
    # skills reference known targets
    for s in reg.skills.values():
        if not s.targets:
            raise RegistryError(f"{s.rel}: skill has no 'targets'")
        bad = set(s.targets) - KNOWN_TARGETS
        if bad:
            raise RegistryError(f"{s.rel}: unknown target(s) {sorted(bad)}")
    # skill extensions (extends_skill/extends_role): pairing, parent existence, no
    # chained extensions, and a real anchor section to splice into
    for s in reg.skills.values():
        err = validate_skill_extension(reg, s.name, s.frontmatter)
        if err:
            raise RegistryError(err)
    # scope: global (default) | project — see validate_skill_scope / Skill.scope
    for s in reg.skills.values():
        err = validate_skill_scope(s.name, s.frontmatter)
        if err:
            raise RegistryError(err)
    # prompts may omit targets (console-only is valid); when targets are set they must be known
    for p in reg.prompts.values():
        bad = set(p.targets) - KNOWN_TARGETS
        if bad:
            raise RegistryError(f"{p.rel}: unknown target(s) {sorted(bad)}")
    # org domains live on graph EFFORTS, never on projects — a project can hold
    # software and marketing work side by side, so a manifest-level `org:` would be a
    # category error. Checked ahead of stage/etc. so an org problem is reported on its
    # own line.
    valid_orgs = known_org_domains(reg)
    for slug, proj in reg.projects.items():
        if proj.get("org"):
            raise RegistryError(
                f"project {slug}: 'org' is no longer a manifest field — org domains "
                f"are tagged per effort in registry/graph/{slug}.jsonld (peccia:orgDomain "
                f"on a CreativeWork node); remove 'org:' from the manifest")
    for slug, pg in reg.graphs.items():
        for e in pg.efforts:
            if e.org_domain and e.org_domain not in valid_orgs:
                raise RegistryError(
                    f"graph {slug}: effort {e.id!r} has unknown org domain "
                    f"{e.org_domain!r}; valid: {', '.join(sorted(valid_orgs))}")
    # project stages valid; context partials exist
    for slug, proj in reg.projects.items():
        stage = proj.get("stage")
        if stage not in VALID_STAGES:
            raise RegistryError(f"project {slug}: invalid stage {stage!r}")
        # `example: true` marks a shipped sample project (steps aside once the user supplies
        # their own overlay projects). Optional, but must be a bool if set — same as machines.
        if "example" in proj and not isinstance(proj["example"], bool):
            raise RegistryError(f"project {slug}: 'example' must be true/false")
        # `description:` feeds the generated Project Roster on Projects/AGENTS.md.
        # Optional, but a set value must be a non-empty string.
        if "description" in proj:
            d = proj["description"]
            if not isinstance(d, str) or not d.strip():
                raise RegistryError(
                    f"project {slug}: 'description' must be a non-empty string")
        repo_raw = proj.get("repo")
        if repo_raw is not None and repo_raw != "":
            if isinstance(repo_raw, str):
                if not repo_raw.strip():
                    raise RegistryError(f"project {slug}: 'repo' must not be empty")
            elif isinstance(repo_raw, list):
                if not repo_raw:
                    raise RegistryError(f"project {slug}: 'repo' list must not be empty")
                for i, url in enumerate(repo_raw):
                    if not isinstance(url, str) or not url.strip():
                        raise RegistryError(
                            f"project {slug}: 'repo' list[{i}] must be a non-empty string")
                seen_urls: set[str] = set()
                seen_basenames: set[str] = set()
                for url in repo_raw:
                    u = url.strip()
                    if u in seen_urls:
                        raise RegistryError(f"project {slug}: duplicate repo URL {u!r}")
                    seen_urls.add(u)
                    bn = _repo_basename(u)
                    if bn in seen_basenames:
                        raise RegistryError(
                            f"project {slug}: repo {u!r} produces checkout dir {bn!r} "
                            f"which collides with another repo in this project — use repos "
                            f"with unique names or host paths")
                    seen_basenames.add(bn)
            else:
                raise RegistryError(
                    f"project {slug}: 'repo' must be a string or a list of strings")
        for mname, raw in (proj.get("local_path") or {}).items():
            if mname not in reg.machines:
                raise RegistryError(
                    f"project {slug}: local_path references unknown machine {mname!r}")
            resolve_local_path(mname, reg.machines[mname], raw)  # fails loudly if a
            # relative entry has no projects_root to resolve against
        # agentic_tree (optional): mounts the full agents-md operating tree (the same
        # Navigation/Workflows/Skills/roster shape a Hermes machine gets at its
        # assistant_root) inside this project's own checkout, at
        # <local_path>/<agentic_tree>/ — the workstation-side counterpart to a machine
        # mount, e.g. so Antigravity can operate against a project like an agentic
        # harness. A single relative subdirectory name, not a path — must not collide
        # with a repo checkout basename landing in the same local_path (both mounts
        # share that directory).
        at = proj.get("agentic_tree")
        if at is not None:
            if not isinstance(at, str) or not at.strip():
                raise RegistryError(
                    f"project {slug}: 'agentic_tree' must be a non-empty string "
                    f"(a subdirectory name under local_path, e.g. 'MitosAgent')")
            at = at.strip()
            if at in (".", "..") or "/" in at or "\\" in at:
                raise RegistryError(
                    f"project {slug}: 'agentic_tree' must be a single directory name, "
                    f"not a path — got {at!r}")
            for url in repo_raw if isinstance(repo_raw, list) else (
                    [repo_raw] if isinstance(repo_raw, str) and repo_raw.strip() else []):
                if _repo_basename(url.strip()) == at:
                    raise RegistryError(
                        f"project {slug}: 'agentic_tree' subdirectory {at!r} collides "
                        f"with the checkout dir of repo {url.strip()!r} — choose a "
                        f"different subdirectory name")
        for label, rel in (proj.get("context") or {}).items():
            rel_in_reg = rel.split("registry/", 1)[-1]
            if rel_in_reg not in reg.partials:
                raise RegistryError(
                    f"project {slug}: context.{label} -> missing partial {rel}"
                )
        # per-project capability binding (the per-project binding design): the named
        # skills/agents must exist; a bound skill must be claude-code-compatible (the
        # manifest decides WHICH projects, the skill's targets: decides WHICH tools).
        for label, key in (("skills", "skills"), ("agents", "agents")):
            val = proj.get(key)
            if val is not None and not isinstance(val, list):
                raise RegistryError(f"project {slug}: '{key}' must be a list")
        for sname in (proj.get("skills") or []):
            if sname not in reg.skills:
                raise RegistryError(
                    f"project {slug}: skills binds unknown skill {sname!r}")
            if not set(reg.skills[sname].targets) & PROJECT_SCOPE_CAPABLE_TARGETS:
                raise RegistryError(
                    f"project {slug}: bound skill {sname!r} does not target "
                    f"{sorted(PROJECT_SCOPE_CAPABLE_TARGETS)} — a project binding only "
                    f"takes effect on a target with a project-scoped skill surface")
            if reg.skills[sname].frontmatter.get("extends_skill"):
                raise RegistryError(
                    f"project {slug}: skills binds {sname!r}, which is an extension "
                    f"(extends_skill) — bind its parent skill instead; extensions "
                    f"deploy only spliced into their parent, never standalone")
        for aname in (proj.get("agents") or []):
            if aname not in reg.agents:
                raise RegistryError(
                    f"project {slug}: agents binds unknown agent {aname!r}")
        for pname in (proj.get("prompts") or []):
            if pname not in reg.prompts:
                raise RegistryError(
                    f"project {slug}: prompts binds unknown prompt {pname!r}")
            if "claude-code" not in reg.prompts[pname].targets:
                raise RegistryError(
                    f"project {slug}: bound prompt {pname!r} does not target "
                    f"'claude-code' — add it to the prompt's targets: to bind it")
        # document_store binds the project to the MCP server that backs its knowledge-graph
        # init (Stage 1 of the graph pipeline). Optional; when set it must name a real server
        # in connections/servers.yaml (or the literal 'none' for a project with no store).
        ds = proj.get("document_store")
        if ds is not None:
            if not isinstance(ds, str):
                raise RegistryError(
                    f"project {slug}: document_store must be a string — a server name from "
                    f"connections/servers.yaml, or 'none'")
            known = set(reg.servers.get("servers") or {}) | {"none"}
            if ds not in known:
                raise RegistryError(
                    f"project {slug}: document_store {ds!r} is not a known MCP server; "
                    f"known: {sorted(known)}")
        # exclude_folders (optional) — folder names or IDs to skip during staging.
        # Each entry must be a non-empty string.
        ef = proj.get("exclude_folders")
        if ef is not None:
            if not isinstance(ef, list) or not all(isinstance(x, str) and x for x in ef):
                raise RegistryError(
                    f"project {slug}: exclude_folders must be a list of non-empty strings "
                    f"(folder names or IDs to skip during staging)")
    # every project graph maps to a real project manifest
    for slug in reg.graphs:
        if slug not in reg.projects:
            raise RegistryError(
                f"graph {slug}.jsonld: no project manifest with slug {slug!r} "
                f"(registry/projects/)")
    # machines reference known targets
    for name, m in reg.machines.items():
        targets = set(m.get("targets", []))
        bad = targets - KNOWN_TARGETS
        if bad:
            raise RegistryError(f"machine {name}: unknown target(s) {sorted(bad)}")
        # Machine roles are exclusive: an agentic-harness machine (hermes) is dedicated
        # to that purpose — it does not also run coding harnesses. This keeps every
        # machine's operating-mount tree (assistant_root) unambiguous and lets the
        # planner's role checks key off "hermes in targets" alone. agents-md itself is
        # NOT a harness (it's the context format both roles can consume — a reference
        # mount via agentic_context_root, or an operating mount via assistant_root or a
        # project's agentic_tree:), so it is never part of this exclusion.
        _CODING_TARGETS = {"antigravity", "claude-app", "claude-code"}
        if "hermes" in targets:
            coding_present = targets & _CODING_TARGETS
            if coding_present:
                raise RegistryError(
                    f"machine {name}: 'hermes' (the agentic harness) cannot share a "
                    f"machine with coding harness target(s) {sorted(coding_present)}. "
                    f"An agentic machine is dedicated to that purpose — put coding "
                    f"harnesses on a separate machine profile.")
        # document_store (optional): the server this machine's assistant is wired to —
        # feeds the generated Connections section (render.connections_block). Same
        # shape/validation as a project's document_store.
        ds = m.get("document_store")
        if ds is not None:
            if not isinstance(ds, str):
                raise RegistryError(
                    f"machine {name}: document_store must be a string — a server name "
                    f"from connections/servers.yaml, or 'none'")
            known = set(reg.servers.get("servers") or {}) | {"none"}
            if ds not in known:
                raise RegistryError(
                    f"machine {name}: document_store {ds!r} is not a known MCP server; "
                    f"known: {sorted(known)}")
        paths = m.get("paths") or {}
        # 1. Detect invalid/control characters in machine path keys (escape sequence bugs)
        for key, pval in paths.items():
            if not pval:
                continue
            val_str = str(pval)
            garbled = re.search(r'[\x00-\x1f\x7f-\x9f\u2028\u2029]', val_str)
            if garbled:
                char_hex = hex(ord(garbled.group(0)))
                raise RegistryError(
                    f"machine {name}: path key '{key}' contains invalid/garbled characters (hex {char_hex}). "
                    f"Ensure you are using forward slashes '/' and not unescaped backslashes '\\' in double-quoted strings.")
        # 2. Prevent agentic_context_root from overlapping with code project checkouts (git pollution/collision)
        ac_root = paths.get("agentic_context_root")
        if ac_root:
            from .io import expand
            ac_root_resolved = expand(resolve_local_path(name, m, ac_root)).resolve()
            for slug, proj in reg.projects.items():
                local = (proj.get("local_path") or {}).get(name)
                if not local:
                    continue
                proj_path = expand(resolve_local_path(name, m, local)).resolve()
                if ac_root_resolved == proj_path or proj_path in ac_root_resolved.parents or ac_root_resolved in proj_path.parents:
                    raise RegistryError(
                        f"machine {name}: 'agentic_context_root' ({ac_root}) must not overlap with "
                        f"project '{slug}' workspace path ({proj_path.as_posix()}). Keep the Agentic Context tree separate "
                        f"from project checkouts to avoid path collisions and git pollution.")
        # 3. `example: true` marks a shipped template profile (skipped by compile once a real
        #    machine exists; refused by a real deploy). Optional, but must be a bool if set.
        if "example" in m and not isinstance(m["example"], bool):
            raise RegistryError(f"machine {name}: 'example' must be true/false")
        # 4. Sync transport (consumed only by `mitos sync`, never the compiler) — validate
        #    its SHAPE here without importing the sync package, so the deterministic verbs
        #    stay free of network code. Sync is git-only: a `git.hub` remote URL.
        sync = m.get("sync")
        if sync is not None:
            if not isinstance(sync, dict):
                raise RegistryError(f"machine {name}: 'sync' must be a mapping")
            backend = sync.get("backend")
            if backend not in (None, "git"):
                raise RegistryError(
                    f"machine {name}: sync.backend {backend!r} is not supported — sync is "
                    f"git-only (omit backend, or set backend: git)")
            git_cfg = sync.get("git") or {}
            if not git_cfg.get("hub"):
                raise RegistryError(
                    f"machine {name}: sync needs sync.git.hub (the overlay repo's remote URL "
                    f"— a self-hosted server or a private GitHub repo)")
            if "ssh_key" in git_cfg and not isinstance(git_cfg["ssh_key"], str):
                raise RegistryError(
                    f"machine {name}: sync.git.ssh_key must be a string path to the private key")
        # 5. hermes_settings (optional): a few Hermes config.yaml runtime knobs this
        #    machine wants Mitos to own via targets/hermes.yaml's `settings:` merge.
        #    terminal.cwd needs no field here — it derives from paths.assistant_root.
        hs = m.get("hermes_settings")
        if hs is not None:
            if not isinstance(hs, dict):
                raise RegistryError(f"machine {name}: 'hermes_settings' must be a mapping")
            for k in ("memory_enabled", "user_profile_enabled"):
                if k in hs and not isinstance(hs[k], bool):
                    raise RegistryError(f"machine {name}: hermes_settings.{k} must be true/false")
            for k in ("max_turns", "restart_drain_timeout"):
                if k in hs and not isinstance(hs[k], int):
                    raise RegistryError(f"machine {name}: hermes_settings.{k} must be an integer")
            for k in ("disabled_toolsets", "platform_toolsets_cli", "platform_toolsets_telegram",
                      "fallback_providers", "custom_providers"):
                if k in hs and not isinstance(hs[k], list):
                    raise RegistryError(f"machine {name}: hermes_settings.{k} must be a list")
            if "session_reset_mode" in hs and not isinstance(hs["session_reset_mode"], str):
                raise RegistryError(
                    f"machine {name}: hermes_settings.session_reset_mode must be a string")
            if "fallback_model" in hs and not isinstance(hs["fallback_model"], dict):
                raise RegistryError(
                    f"machine {name}: hermes_settings.fallback_model must be a mapping")
        # 6. skills (optional): per-target curation of the compatible skill set —
        #    `{<target>: {include: [...] | exclude: [...]}}`. The overlayable home for
        #    what target-side skills.include/exclude used to do (rejected above); this
        #    machine's box, this machine's file. include/exclude follow the same rules
        #    the old target-side keys did: names must exist, no skill in both.
        msk = m.get("skills")
        if msk is not None:
            if not isinstance(msk, dict):
                raise RegistryError(f"machine {name}: 'skills' must be a mapping of "
                                    f"target -> {{include/exclude}}")
            bad_targets = set(msk) - KNOWN_TARGETS
            if bad_targets:
                raise RegistryError(f"machine {name}: skills references unknown "
                                    f"target(s) {sorted(bad_targets)}")
            for tname, curation in msk.items():
                if not isinstance(curation, dict):
                    raise RegistryError(
                        f"machine {name}: skills.{tname} must be a mapping "
                        f"({{include: [...]}} or {{exclude: [...]}})")
                inc, exc = curation.get("include"), curation.get("exclude")
                for label, lst in (("include", inc), ("exclude", exc)):
                    if lst is None:
                        continue
                    if not isinstance(lst, list):
                        raise RegistryError(
                            f"machine {name}: skills.{tname}.{label} must be a list")
                    bad = set(lst) - set(reg.skills)
                    if bad:
                        raise RegistryError(
                            f"machine {name}: skills.{tname}.{label} references "
                            f"unknown skill(s) {sorted(bad)}")
                both = set(inc or []) & set(exc or [])
                if both:
                    raise RegistryError(
                        f"machine {name}: skills.{tname} lists skill(s) in BOTH "
                        f"include and exclude: {sorted(both)}")
    # Skill curation (include:/exclude:) is a PERSONAL choice — which of the compatible
    # skills a given box actually wants — not compiler spec. targets/*.yaml is core and
    # NOT overlayable (see AGENTS.md), so a curation list living there is a fork tax on
    # every community user who wants a different set. It belongs on the machine profile
    # instead (registry/local/machines/<name>.yaml is overlayable). Reject it loudly here
    # rather than silently ignoring it, so a stale core edit or a misplaced local edit
    # fails fast instead of quietly doing nothing.
    for tname, tspec in reg.targets.items():
        sk = tspec.get("skills") or {}
        if "include" in sk or "exclude" in sk:
            raise RegistryError(
                f"target {tname}: skills.include/exclude is not allowed in targets/*.yaml "
                f"(core, not overlayable) — set it on the machine profile instead: "
                f"machines/<name>.yaml's `skills: {{{tname}: {{include: [...]}}}}`")
    # machine-side skill curation (the overlayable equivalent): validated below,
    # alongside the rest of machine profile validation.
    # servers.yaml shape; per-machine URL overrides reference known machines
    if "servers" not in reg.servers:
        raise RegistryError("connections/servers.yaml: missing top-level 'servers'")
    for name, server in (reg.servers.get("servers") or {}).items():
        bad = set(server.get("urls") or {}) - set(reg.machines)
        if bad:
            raise RegistryError(f"servers.{name}: urls reference unknown machine(s) "
                                f"{sorted(bad)}")
        bad = set(server.get("hosted_on") or []) - set(reg.machines)
        if bad:
            raise RegistryError(f"servers.{name}: hosted_on references unknown "
                                f"machine(s) {sorted(bad)}")
        # graph_enum (optional) tells the backend-agnostic `mcp` connector HOW to enumerate
        # this store's documents for knowledge-graph init: which MCP tool lists files, and how
        # its returned fields map onto the lean {id, name, dateModified, webUrl, type} shape
        # (`type` optional — the store's MIME/kind field, stored as schema:additionalType).
        # The connector stays generic; each server describes itself.
        enum = server.get("graph_enum")
        if enum is not None:
            if not isinstance(enum, dict):
                raise RegistryError(f"servers.{name}: graph_enum must be a mapping")
            if not enum.get("list_tool"):
                raise RegistryError(
                    f"servers.{name}: graph_enum.list_tool is required (the MCP tool that "
                    f"lists documents)")
            fields = enum.get("fields") or {}
            if not isinstance(fields, dict):
                raise RegistryError(f"servers.{name}: graph_enum.fields must be a mapping")
            for req in ("id", "name"):
                if req not in fields:
                    raise RegistryError(
                        f"servers.{name}: graph_enum.fields must map {req!r} to the tool's "
                        f"field name")
            text_fields = enum.get("text_fields")
            if text_fields is not None and not isinstance(text_fields, dict):
                raise RegistryError(
                    f"servers.{name}: graph_enum.text_fields must be a mapping of "
                    f"field-name → one-capture-group regex")
            page_size = enum.get("page_size")
            if page_size is not None and not isinstance(page_size, int):
                raise RegistryError(
                    f"servers.{name}: graph_enum.page_size must be an integer")
        # exclude_folders (optional) lists folder names or IDs to skip when this server's
        # store is enumerated for knowledge-graph staging. Each entry must be a non-empty string.
        ef = server.get("exclude_folders")
        if ef is not None:
            if not isinstance(ef, list) or not all(isinstance(x, str) and x for x in ef):
                raise RegistryError(
                    f"servers.{name}: exclude_folders must be a list of non-empty strings "
                    f"(folder names or IDs to skip during staging)")

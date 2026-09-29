"""Load and validate the registry, target specs, and machine profiles.

Validation fails loudly: unknown audiences, bad project stages, missing partials, and
dangling references are errors, not warnings. Schema validation is the first test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KNOWN_TARGETS = {"claude-code", "antigravity", "context-tree", "claude-app"}
VALID_STAGES = {"ideation", "speccing", "build", "maintain"}
VALID_SKILL_SCOPES = {"global", "project"}
# Targets with a project-scoped skill deploy path (claude-code: <local_path>/.claude/skills/,
# antigravity: <local_path>/.agents/skills/) — the only targets a project's `skills:` list
# binds a skill for, and the only targets where `scope: project` changes anything. claude-app
# has no project-scoped surface at all (account-wide/global only) and simply
# IGNORES `scope` — always global, on any skill, regardless of value.
# See validate_skill_scope / Skill.scope.
PROJECT_SCOPE_CAPABLE_TARGETS = {"claude-code", "antigravity"}


def is_manual_skill_target(tspec: dict) -> bool:
    """Whether this target's skill lane ends with a human, rather than with the compiler.

    `mode: zip` is that set by construction: it exists precisely because claude.ai exposes no
    filesystem to write and no upload API, so the compiler can only stage a file for someone to
    upload (targets/claude-app.yaml). Nothing else emits skills that way.

    A manual target stages a MENU. It takes no curation, and it deploys nothing that could leak
    a `scope: project` skill globally — the human decides both, at upload time."""
    return ((tspec or {}).get("skills") or {}).get("mode") == "zip"


# The registry-wide user config (registry/user.yaml + registry/local/user.yaml overlay).
# Resolved core-then-overlay with last-layer-wins:
#
#   IDENTITY — the personalization placeholders render.py expands ({{user_given_name}},
#     {{users_given_name}}, {{user_full_name}}, {{user_email}}, {{user_location}}). These
#     are the file's contents.
#
# Only IDENTITY keys become template tokens. render.user_token_map iterates a fixed
# _USER_TOKENS list, never reg.user's keys.
#
# A fixed, closed schema — unknown keys are rejected loudly rather than silently ignored,
# the same posture as every other registry file.
KNOWN_USER_KEYS = {"given_name", "full_name", "email", "location"}
RETIRED_USER_KEYS = {"default_deliverables"}
KNOWN_AGENT_KEYS = {"name", "description", "targets", "goal", "skills"}
_DEFAULT_USER = {"given_name": "User", "full_name": "Mitos User",
                 "email": "user@example.com", "location": "Your City, State"}

# Supporting-file subdirectories a skill folder may carry alongside SKILL.md —
# auto-deployed next to the rendered SKILL.md and bundled into claude-app zips.
# The set is the union of the harnesses' documented conventions: examples/ + scripts/
# (Claude Code, Antigravity), references/ + templates/ (the assistant harness), resources/
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
        (the antigravity_skills dir, claude-app zips). `project`: deploys ONLY
        into the project checkouts that bind it via that project's `skills:` list —
        never a global directory; see validate_skill_scope."""
        return self.frontmatter.get("scope", "global")

    @property
    def requires_server(self) -> str | None:
        """The MCP server (a `connections/servers.yaml` key) this skill is useless
        without — e.g. the `gws` skill is nothing but instructions for driving the `gws`
        server's tools. Optional; omit for a skill that stands on its own.

        A machine declares the connections it actually has via its `document_store:`
        (the same field render.connections_block reads to decide which connection
        sections a node may name). planner._selected_skills drops a skill whose required
        server this machine never declared, so a coding-harness box with no workspace
        wired never receives instructions for tools it cannot call."""
        return self.frontmatter.get("requires_server") or None


@dataclass
class Prompt:
    """A harness-agnostic reusable prompt, authored in registry/prompts/<name>.md.
    The substrate every harness understands. Skills are progressive enhancement
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
class Agent:
    """An agent authored in registry/agents/<name>.md (or registry/local/agents/).
    Curated per machine under `agents: {include: [...] | exclude: [...]}`."""
    name: str
    description: str
    targets: list[str] = field(default_factory=list)
    goal: str = ""
    skills: list[str] = field(default_factory=list)
    body: str = ""
    source: Path = field(default_factory=lambda: Path("."))
    harness_blocks: dict[str, Any] = field(default_factory=dict)

    @property
    def frontmatter(self) -> dict:
        fm = {
            "name": self.name,
            "description": self.description,
            "targets": list(self.targets),
        }
        if self.goal:
            fm["goal"] = self.goal
        if self.skills:
            fm["skills"] = list(self.skills)
        if self.harness_blocks:
            for k, v in self.harness_blocks.items():
                fm[k] = v
        return fm

    @property
    def rel(self) -> str:
        parts = self.source.parts
        if "registry" in parts:
            idx = parts.index("registry")
            return "/".join(parts[idx + 1:])
        return self.source.as_posix()


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
    prompts: dict = field(default_factory=dict)  # name -> Prompt (registry/prompts/)
    user: dict = field(default_factory=lambda: dict(_DEFAULT_USER))  # given_name,
                                   # full_name, email, location — core defaults merged
                                   # with registry/local/user.yaml (field-level overlay)
    agents: dict[str, Agent] = field(default_factory=dict)  # name -> Agent (registry/agents/)
    warnings: list[str] = field(default_factory=list)
    skipped_machines: dict[str, list[str]] = field(default_factory=dict)

    @property
    def target_names(self) -> set[str]:
        return set(self.targets.keys())

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


def _load_user(dir_path: Path, label: str) -> tuple[dict, list[str]]:
    """One layer of user.yaml (core or overlay) — {} when the file is absent, so a
    hermetic test registry without one still loads fine (the dataclass default supplies
    neutral values). Unlike `_load_yaml`, an empty file is valid (yaml.safe_load returns
    None) rather than a schema error, since a scaffolded overlay may start blank."""
    path = dir_path / "user.yaml"
    if not path.is_file():
        return {}, []
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{label}: must be a YAML mapping")
    warnings: list[str] = []
    lines = text.splitlines()
    for k in sorted(data):
        if k in RETIRED_USER_KEYS:
            line_no = next((idx for idx, line in enumerate(lines, 1)
                            if re.match(rf"^\s*{re.escape(k)}\s*:", line)), None)
            loc = f" line {line_no}" if line_no else ""
            warnings.append(f"{label}{loc}: '{k}' in user.yaml is retired — delete this line")
    clean_data = {k: v for k, v in data.items() if k not in RETIRED_USER_KEYS}
    bad = set(clean_data) - KNOWN_USER_KEYS
    if bad:
        raise RegistryError(f"{label}: unknown key(s) {sorted(bad)} — known: "
                            f"{sorted(KNOWN_USER_KEYS)}")
    for k, v in clean_data.items():
        if not isinstance(v, str):
            raise RegistryError(f"{label}: {k!r} must be a string")
    return clean_data, warnings


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{path} must be a YAML mapping")
    return data


def load(root: Path, ignore_local: bool = False) -> Registry:
    reg_dir = root / "registry"
    if not reg_dir.is_dir():
        raise RegistryError(f"no registry/ directory at {root}")

    user_warnings: list[str] = []
    partials = _load_partials(reg_dir)
    skills = _load_skills(reg_dir)
    prompts = _load_prompts(reg_dir)
    projects = _load_projects(reg_dir)
    graphs = _load_graphs(reg_dir)
    core_user, w = _load_user(reg_dir, "registry/user.yaml")
    user_warnings.extend(w)
    user = {**_DEFAULT_USER, **core_user}

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
        prompts = _overlay(prompts, _load_prompts(local_dir, prefix=pfx))
        local_projects = _load_projects(local_dir, is_local=True)
        projects = _overlay(projects, local_projects)
        graphs = _overlay(graphs, _load_graphs(local_dir))
        overlay_user, w = _load_user(local_dir, "registry/local/user.yaml")
        user_warnings.extend(w)
        user = {**user, **overlay_user}

    # MCP servers are moat TOOLS, not registry content — they live in connections/
    # (own deploy lane); see the connections-lane design.
    conn = root / "connections" / "servers.yaml"
    if not conn.is_file():
        raise RegistryError(f"missing {conn} — MCP servers live in connections/")
    servers = _load_yaml(conn)
    targets = _load_dir_of_yaml(root / "targets", key="target")
    machines = _load_dir_of_yaml(root / "machines", key="name")

    # Mitos overlay for targets, machines and connections: targets are add-only
    # (same-name overlay target is an error, Q1). Private machine profiles with
    # real hostnames/IPs and server configs with LAN addresses live in registry/local/ (gitignored).
    if local_dir.is_dir() and not ignore_local:
        local_targets_dir = local_dir / "targets"
        if local_targets_dir.is_dir() and any(local_targets_dir.glob("*.yaml")):
            local_targets = _load_dir_of_yaml(local_targets_dir, key="target")
            collision = set(targets) & set(local_targets)
            if collision:
                raise RegistryError(f"overlay target collisions not allowed: {sorted(collision)}")
            targets.update(local_targets)
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

    reg_warnings: list[str] = list(user_warnings)
    for pg in graphs.values():
        reg_warnings.extend(pg.warnings)
    reg = Registry(root=root, partials=partials, skills=skills, servers=servers,
                   projects=projects, targets=targets, machines=machines, graphs=graphs,
                   prompts=prompts, user=user, warnings=reg_warnings)
    reg.agents = _load_agents(reg, ignore_local=ignore_local)
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


def validate_agent_file_content(text: str, rel: str, stem: str, skills: dict[str, Skill],
                                source: Path | None = None,
                                known_targets: set[str] | None = None,
                                targets_spec: dict[str, dict] | None = None,
                                warnings: list[str] | None = None) -> tuple[Agent | None, str | None]:
    """Validate an agent Markdown document (frontmatter + body).
    Returns (Agent, None) on success, or (None, error_str) on failure."""
    try:
        meta, body = _split_frontmatter(text, rel)
    except RegistryError as e:
        return None, str(e)

    # 1. Inspect frontmatter keys: known keys vs mapping blocks vs scalar keys
    harness_blocks: dict[str, Any] = {}
    bad_scalars: list[str] = []
    for k, v in meta.items():
        if k in KNOWN_AGENT_KEYS:
            continue
        if isinstance(v, dict):
            harness_blocks[k] = v
        else:
            bad_scalars.append(k)

    if bad_scalars:
        return None, f"{rel}: unknown frontmatter key(s) {sorted(bad_scalars)} — known: {sorted(KNOWN_AGENT_KEYS)}"

    # 2. Required fields: name, description, targets
    name = meta.get("name")
    if not name or not isinstance(name, str):
        return None, f"{rel}: agent missing or empty 'name'"
    if stem and name != stem:
        return None, f"{rel}: agent 'name' {name!r} does not match filename stem {stem!r}"
    if not re.fullmatch(r"[a-z0-9-]+", name):
        return None, f"{rel}: agent 'name' {name!r} is not a valid slug (lowercase [a-z0-9-]+)"

    desc = meta.get("description")
    if not desc or not isinstance(desc, str) or not desc.strip():
        return None, f"{rel}: agent missing or empty 'description'"

    if "targets" not in meta or meta.get("targets") is None:
        return None, f"{rel}: agent has no 'targets'"
    targets_val = meta.get("targets")
    if not isinstance(targets_val, list) or not targets_val:
        return None, f"{rel}: agent has no 'targets'"
    if not all(isinstance(t, str) and t.strip() for t in targets_val):
        return None, f"{rel}: agent 'targets' must be a list of strings"
    targets = [t.strip() for t in targets_val]
    if known_targets is not None:
        bad_targets = set(targets) - known_targets
        if bad_targets:
            return None, f"{rel}: unknown target(s) {sorted(bad_targets)}"

    # 3. Portable fields: goal, skills
    goal_val = meta.get("goal")
    if goal_val is not None and not isinstance(goal_val, str):
        return None, f"{rel}: agent 'goal' must be a string"
    goal = str(goal_val or "").strip()

    skills_val = meta.get("skills")
    if skills_val is not None:
        if not isinstance(skills_val, list) or not all(isinstance(s, str) and s.strip() for s in skills_val):
            return None, f"{rel}: agent 'skills' must be a list of strings"
        sk_list = [s.strip() for s in skills_val]
    else:
        sk_list = []

    # 4. Validate skills
    for s in sk_list:
        if s not in skills:
            return None, f"{rel}: agent {name!r} references unknown skill {s!r}"
        for t in targets:
            if t not in skills[s].targets:
                return None, f"{rel}: agent {name!r} references skill {s!r} whose targets do not include '{t}'"

    # 5. ARB-03 harness blocks: unknown block warns, target-block not in targets warns
    for k in harness_blocks:
        if known_targets is not None:
            if k in known_targets:
                if k not in targets:
                    msg = f"{rel}: block ignored: '{k}' not in targets"
                    if warnings is not None:
                        warnings.append(msg)
            else:
                msg = f"{rel}: unknown block '{k}' ignored"
                if warnings is not None:
                    warnings.append(msg)

    # 6. Target supports_skills: false check
    if targets_spec is not None and warnings is not None and sk_list:
        for t in targets:
            tspec = targets_spec.get(t) or {}
            ag_spec = tspec.get("agents") or {}
            if ag_spec.get("supports_skills") is False:
                msg = f"agent {name!r}: target '{t}' has supports_skills: false"
                if msg not in warnings:
                    warnings.append(msg)

    agent = Agent(
        name=name,
        description=desc.strip(),
        targets=targets,
        goal=goal,
        skills=sk_list,
        body=body.strip("\n"),
        source=source or Path(rel),
        harness_blocks=harness_blocks,
    )
    return agent, None


def _load_agents_dir(adir: Path, skills: dict[str, Skill], root: Path,
                     reg: Registry | None = None) -> dict[str, Agent]:
    out: dict[str, Agent] = {}
    if not adir.is_dir():
        return out
    known_targets = reg.target_names if reg is not None else None
    targets_spec = reg.targets if reg is not None else None
    warnings = reg.warnings if reg is not None else None
    for af in sorted(adir.glob("*.md")):
        try:
            rel = af.relative_to(root).as_posix()
        except ValueError:
            rel = af.as_posix()
        agent, err = validate_agent_file_content(
            af.read_text(encoding="utf-8"), rel, af.stem, skills, af,
            known_targets=known_targets, targets_spec=targets_spec, warnings=warnings
        )
        if err:
            raise RegistryError(err)
        out[agent.name] = agent
    return out


def _load_agents(reg_or_root: Registry | Path, skills: dict[str, Skill] | None = None, *, ignore_local: bool = False) -> dict[str, Agent]:
    """Load agents from registry/agents/*.md and registry/local/agents/*.md with
    last-layer-wins precedence."""
    reg = reg_or_root if isinstance(reg_or_root, Registry) else None
    if isinstance(reg_or_root, Registry):
        root = reg_or_root.root
        reg_skills = reg_or_root.skills if skills is None else skills
    else:
        root = reg_or_root
        reg_skills = skills or {}
    core_dir = root / "registry"
    local_dir = core_dir / LOCAL_OVERLAY
    out = _load_agents_dir(core_dir / "agents", reg_skills, root, reg=reg)
    if local_dir.is_dir() and not ignore_local:
        local_out = _load_agents_dir(local_dir / "agents", reg_skills, root, reg=reg)
        out = _overlay(out, local_out)
    return out


def selected_agents(reg: Registry, machine: dict, target: str | None = None) -> list[str]:
    """Active agents deployed to a machine.
    If target is given, only agents that include that target in their targets:
    and the machine runs that target are selected.
    Curated via optional machine-side `agents: {include: [...] | exclude: [...]}`."""
    machine_targets = set(machine.get("targets") or [])
    if target is not None:
        if target not in machine_targets:
            return []
        candidates = [a for a in reg.agents.values() if target in a.targets]
    else:
        candidates = [a for a in reg.agents.values() if any(t in machine_targets for t in a.targets)]

    mag = machine.get("agents") or {}
    inc = mag.get("include")
    exc = set(mag.get("exclude") or [])
    if inc is not None:
        selected = [a.name for a in candidates if a.name in inc]
    else:
        selected = [a.name for a in candidates if a.name not in exc]
    return selected




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


def document_stores(raw) -> list[str]:
    """Normalize an already-validated `document_store:` value (project or machine) to a list
    of server names for iteration. A single string (the common case) becomes a one-item
    list; a list passes through; None/absent is empty. The stored manifest value itself is
    never rewritten by validation — a plain string stays valid forever, no migration — so
    call this wherever a store needs to be iterated (Stage 3 connect, the generated
    connection sections); single-store code paths may keep reading the raw value directly."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _check_document_store(label: str, ds, known: set[str]) -> None:
    """Validate a `document_store:` value shared by project and machine manifests: a string
    OR a list of strings ("multi connections" — a project's/machine's graph may draw from
    more than one server; explicitly NOT multi-account-per-server-type, so the server key
    stays identity everywhere). Each entry must be a known server name or the literal
    'none'; duplicates and an empty list are rejected loudly. 'none' cannot be combined with
    a real store — it means "no store", which is contradictory alongside one."""
    if isinstance(ds, str):
        values = [ds]
    elif isinstance(ds, list) and all(isinstance(v, str) for v in ds):
        values = ds
    else:
        raise RegistryError(
            f"{label}: document_store must be a string or a list of strings — a server "
            f"name from connections/servers.yaml, or 'none'")
    if not values:
        raise RegistryError(f"{label}: document_store list must not be empty")
    if len(values) != len(set(values)):
        raise RegistryError(f"{label}: document_store lists a duplicate server name")
    if "none" in values and len(values) > 1:
        raise RegistryError(
            f"{label}: document_store 'none' cannot be combined with other stores")
    bad = [v for v in values if v not in known]
    if bad:
        raise RegistryError(
            f"{label}: document_store {bad!r} is not a known MCP server; "
            f"known: {sorted(known)}")


def validate_skill_scope(skill_name: str, frontmatter: dict) -> str | None:
    """Cross-check a skill's `scope` frontmatter key. Returns an error string, or None
    when valid. No per-target incompatibility to check: a target with no project-scoped
    surface (claude-app) simply ignores `scope` and always deploys globally, so
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
            if "agents-md" in p.audience:
                raise RegistryError(f"{p.rel}: audience 'agents-md' is retired — use 'context-tree'")
            bad = set(p.audience) - reg.target_names
            if bad:
                raise RegistryError(f"{p.rel}: unknown audience(s) {sorted(bad)}")
    # skills reference known targets
    for s in reg.skills.values():
        if "agents-md" in s.targets:
            raise RegistryError(f"{s.rel}: target 'agents-md' is retired — use 'context-tree'")
        if not s.targets:
            raise RegistryError(f"{s.rel}: skill has no 'targets'")
        bad = set(s.targets) - reg.target_names
        if bad:
            raise RegistryError(f"{s.rel}: unknown target(s) {sorted(bad)}")
    for pr in reg.prompts.values():
        if "agents-md" in pr.targets:
            raise RegistryError(f"{pr.rel}: target 'agents-md' is retired — use 'context-tree'")
    # scope: global (default) | project — see validate_skill_scope / Skill.scope
    for s in reg.skills.values():
        err = validate_skill_scope(s.name, s.frontmatter)
        if err:
            raise RegistryError(err)
    # requires_server: a connection gate — see Skill.requires_server /
    # planner._selected_skills. Validated against connections/servers.yaml so a typo
    # fails at compile rather than silently suppressing the skill on every machine.
    known_servers = set((reg.servers.get("servers") or {}).keys())
    for s in reg.skills.values():
        req = s.requires_server
        if req and req not in known_servers:
            raise RegistryError(
                f"skill {s.name!r}: requires_server {req!r} is not a server in "
                f"connections/servers.yaml; known: {', '.join(sorted(known_servers))}")
    # agents: valid slug, non-empty description, valid targets, skills must deploy to each target
    for agent in reg.agents.values():
        if "agents-md" in agent.targets:
            raise RegistryError(f"{agent.rel}: target 'agents-md' is retired — use 'context-tree'")
        if not re.fullmatch(r"[a-z0-9-]+", agent.name):
            raise RegistryError(f"agent {agent.name!r} is not a valid slug (lowercase [a-z0-9-]+)")
        if not agent.description or not agent.description.strip():
            raise RegistryError(f"agent {agent.name!r}: missing or empty 'description'")
        if not agent.targets:
            raise RegistryError(f"{agent.rel}: agent has no 'targets'")
        bad_t = set(agent.targets) - reg.target_names
        if bad_t:
            raise RegistryError(f"{agent.rel}: unknown target(s) {sorted(bad_t)}")
        for s in agent.skills:
            if s not in reg.skills:
                raise RegistryError(f"agent {agent.name!r} references unknown skill {s!r}")
            for t in agent.targets:
                if t not in reg.skills[s].targets:
                    raise RegistryError(
                        f"agent {agent.name!r} references skill {s!r} whose targets do not include '{t}'"
                    )
        for t in agent.targets:
            tspec = reg.targets.get(t) or {}
            ag_spec = tspec.get("agents") or {}
            if ag_spec.get("supports_skills") is False and agent.skills:
                msg = f"agent {agent.name!r}: target '{t}' has supports_skills: false"
                if msg not in reg.warnings:
                    reg.warnings.append(msg)
        for k in agent.harness_blocks:
            if k in reg.target_names:
                if k not in agent.targets:
                    msg = f"{agent.rel}: block ignored: '{k}' not in targets"
                    if msg not in reg.warnings:
                        reg.warnings.append(msg)
            else:
                msg = f"{agent.rel}: unknown block '{k}' ignored"
                if msg not in reg.warnings:
                    reg.warnings.append(msg)
    # prompts may omit targets (console-only is valid); when targets are set they must be known
    for p in reg.prompts.values():
        bad = set(p.targets) - reg.target_names
        if bad:
            raise RegistryError(f"{p.rel}: unknown target(s) {sorted(bad)}")
    # org domains live on graph EFFORTS, never on projects — a project can hold
    # software and marketing work side by side, so a manifest-level `org:` would be a
    # category error. Checked ahead of stage/etc. so an org problem is reported on its
    # own line.
    for slug, proj in reg.projects.items():
        if proj.get("org"):
            raise RegistryError(
                f"project {slug}: 'org' is no longer a manifest field — org domains "
                f"are tagged per effort in registry/graph/{slug}.jsonld (peccia:orgDomain "
                f"on a CreativeWork node); remove 'org:' from the manifest")
        if "agents" in proj:
            raise RegistryError(
                f"project {slug}: 'agents' is not a manifest field — agents are registry "
                f"resources in registry/agents/, curated per machine under `agents:`")
        if "aliases" in proj:
            aliases = proj["aliases"]
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                raise RegistryError(
                    f"project {slug}: 'aliases' must be a list of strings")
            for a in aliases:
                if not a.strip():
                    raise RegistryError(
                        f"project {slug}: alias in 'aliases' cannot be empty")
                if "]" in a or "_" in a:
                    raise RegistryError(
                        f"project {slug}: alias {a!r} contains invalid character (']' or '_')")
    # project stages valid; context partials exist
    for slug, proj in reg.projects.items():
        stage = proj.get("stage")
        if stage not in VALID_STAGES:
            raise RegistryError(f"project {slug}: invalid stage {stage!r}")
        # `example: true` marks a shipped sample project (steps aside once the user supplies
        # their own overlay projects). Optional, but must be a bool if set — same as machines.
        if "example" in proj and not isinstance(proj["example"], bool):
            raise RegistryError(f"project {slug}: 'example' must be true/false")
        # `hidden: true` — a finished/parked project stays in the registry and graph
        # (still loads, still queries) but plans no output on any machine (planner._visible_projects
        # is the single choke point). Reusing `stage:` was considered and rejected: a `maintain`
        # project still needs context, so stage cannot double as visibility. Optional, default
        # absent/false, same bool-or-nothing shape as `example`.
        if "hidden" in proj and not isinstance(proj["hidden"], bool):
            raise RegistryError(f"project {slug}: 'hidden' must be true/false")
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
        # `repo_notes:` (optional): a one-line description per repo, keyed by the repo's
        # checkout basename (the same identity `repo_notes`/Workspace Layout/clone-dest all
        # key off) — never by URL, which is what actually varies across owners/hosts. Feeds
        # the generated `## Workspace Layout` section (graph.project_full_markdown) so a
        # project's prose partial never has to hand-list what the manifest already states.
        notes_raw = proj.get("repo_notes")
        if notes_raw is not None and notes_raw != {}:
            if not isinstance(notes_raw, dict):
                raise RegistryError(f"project {slug}: 'repo_notes' must be a mapping "
                                    f"of repo basename to description")
            known_basenames = {
                _repo_basename(u) for u in (
                    repo_raw if isinstance(repo_raw, list)
                    else ([repo_raw] if isinstance(repo_raw, str) and repo_raw.strip()
                          else []))}
            for key, val in notes_raw.items():
                if key not in known_basenames:
                    raise RegistryError(
                        f"project {slug}: repo_notes key {key!r} does not match any "
                        f"'repo' checkout basename; known: {sorted(known_basenames)}")
                if not isinstance(val, str) or not val.strip():
                    raise RegistryError(
                        f"project {slug}: repo_notes[{key!r}] must be a non-empty string")
        # `repo_branches:` (optional): a branch to check out per repo, keyed by the repo's
        # checkout basename — same identity/validation as `repo_notes:`. Absent = the repo's
        # default branch. Deploy checks out the named branch on clone and fast-forwards it on
        # subsequent deploys (commands._git_clone/_git_pull); the harness never writes a repo.
        branches_raw = proj.get("repo_branches")
        if branches_raw is not None and branches_raw != {}:
            if not isinstance(branches_raw, dict):
                raise RegistryError(f"project {slug}: 'repo_branches' must be a mapping "
                                    f"of repo basename to branch name")
            known_basenames = {
                _repo_basename(u) for u in (
                    repo_raw if isinstance(repo_raw, list)
                    else ([repo_raw] if isinstance(repo_raw, str) and repo_raw.strip()
                          else []))}
            for key, val in branches_raw.items():
                if key not in known_basenames:
                    raise RegistryError(
                        f"project {slug}: repo_branches key {key!r} does not match any "
                        f"'repo' checkout basename; known: {sorted(known_basenames)}")
                if not isinstance(val, str) or not val.strip():
                    raise RegistryError(
                        f"project {slug}: repo_branches[{key!r}] must be a non-empty string")
        # `repo_ssh_keys:` (optional): the private key to authenticate a repo's clone/pull
        # with, keyed by checkout basename — same identity/validation as `repo_notes:`/
        # `repo_branches:`. Absent = the ambient default git/ssh identity. A bare filename
        # resolves to `~/.ssh/<name>` on whichever machine runs the clone (agentic.sshkey),
        # so the SAME manifest entry works across every machine that carries that key under
        # that name — no per-machine config needed.
        keys_raw = proj.get("repo_ssh_keys")
        if keys_raw is not None and keys_raw != {}:
            if not isinstance(keys_raw, dict):
                raise RegistryError(f"project {slug}: 'repo_ssh_keys' must be a mapping "
                                    f"of repo basename to a key name/path")
            known_basenames = {
                _repo_basename(u) for u in (
                    repo_raw if isinstance(repo_raw, list)
                    else ([repo_raw] if isinstance(repo_raw, str) and repo_raw.strip()
                          else []))}
            for key, val in keys_raw.items():
                if key not in known_basenames:
                    raise RegistryError(
                        f"project {slug}: repo_ssh_keys key {key!r} does not match any "
                        f"'repo' checkout basename; known: {sorted(known_basenames)}")
                if not isinstance(val, str) or not val.strip():
                    raise RegistryError(
                        f"project {slug}: repo_ssh_keys[{key!r}] must be a non-empty string")
        for mname, raw in (proj.get("local_path") or {}).items():
            if mname not in reg.machines:
                raise RegistryError(
                    f"project {slug}: local_path references unknown machine {mname!r}")
            resolve_local_path(mname, reg.machines[mname], raw)  # fails loudly if a
            # relative entry has no projects_root to resolve against
        # agentic_tree (optional): mounts the full agents-md operating tree (the same
        # Navigation/Workflows/Skills/roster shape a context-tree machine gets at its
        # context_root) inside this project's own checkout, at
        # <local_path>/<agentic_tree>/ — the workstation-side counterpart to a machine
        # mount, e.g. so Antigravity can operate against a project like an agentic
        # harness. A single relative subdirectory name, not a path — must not collide
        # with a repo checkout basename landing in the same local_path (both mounts
        # share that directory).
        if "agentic_tree" in proj:
            raise RegistryError(f"project {slug}: 'agentic_tree' is retired — use 'context_tree'")
        ct = proj.get("context_tree")
        if ct is not None:
            if not isinstance(ct, str) or not ct.strip():
                raise RegistryError(
                    f"project {slug}: 'context_tree' must be a non-empty string "
                    f"(a subdirectory name under local_path, e.g. 'ContextTree')")
            ct = ct.strip()
            if ct in (".", "..") or "/" in ct or "\\" in ct:
                raise RegistryError(
                    f"project {slug}: 'context_tree' must be a single directory name, "
                    f"not a path — got {ct!r}")
            for url in repo_raw if isinstance(repo_raw, list) else (
                    [repo_raw] if isinstance(repo_raw, str) and repo_raw.strip() else []):
                if _repo_basename(url.strip()) == ct:
                    raise RegistryError(
                        f"project {slug}: 'context_tree' subdirectory {ct!r} collides "
                        f"with the checkout dir of repo {url.strip()!r} — choose a "
                        f"different subdirectory name")
        for label, rel in (proj.get("context") or {}).items():
            rel_in_reg = rel.split("registry/", 1)[-1]
            if rel_in_reg not in reg.partials:
                raise RegistryError(
                    f"project {slug}: context.{label} -> missing partial {rel}"
                )
        # per-project capability binding (the per-project binding design): the named
        # skills must exist; a bound skill must be claude-code-compatible (the
        # manifest decides WHICH projects, the skill's targets: decides WHICH tools).
        for label, key in (("skills", "skills"),):
            val = proj.get(key)
            if val is not None and not isinstance(val, list):
                raise RegistryError(f"project {slug}: '{key}' must be a list")
        for sname in (proj.get("skills") or []):
            if sname not in reg.skills:
                raise RegistryError(
                    f"project {slug}: skills binds unknown skill {sname!r}")
            capable = {t for t, spec in reg.targets.items() if spec.get("project_surface")}
            if not set(reg.skills[sname].targets) & capable:
                raise RegistryError(
                    f"project {slug}: bound skill {sname!r} does not target "
                    f"{sorted(capable)} — a project binding only "
                    f"takes effect on a target with a project-scoped skill surface")
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
            known = set(reg.servers.get("servers") or {}) | {"none"}
            _check_document_store(f"project {slug}", ds, known)
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
        if "agents-md" in targets:
            raise RegistryError(f"machine {name}: target 'agents-md' is retired — use 'context-tree'")
        bad = targets - reg.target_names
        if bad:
            reg.skipped_machines[name] = sorted(bad)
            for t in sorted(bad):
                reg.warnings.append(
                    f"machine {name}: target '{t}' is not defined — machine skipped. "
                    f"If a harness supplies this target, accept its seed in the inbox (mitos review)."
                )
            continue
        # document_store (optional): the server this machine's assistant is wired to —
        # feeds the generated Connections section (render.connections_block). Same
        # shape/validation as a project's document_store.
        ds = m.get("document_store")
        if ds is not None:
            known = set(reg.servers.get("servers") or {}) | {"none"}
            _check_document_store(f"machine {name}", ds, known)
        paths = m.get("paths") or {}
        if "assistant_root" in paths:
            raise RegistryError(f"machine {name}: path 'assistant_root' is retired — use 'context_root'")
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
        # 5. (retired) The third-party settings-merge lane is gone — each harness owns its
        #    own config file whole, so there is no third-party
        #    config.yaml to reach settings leaves into. Unknown machine keys are silently
        #    ignored (machine keys are not a closed set), so profiles drop retired settings
        #    blocks explicitly rather than relying on a validation error to catch them.
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
            bad_targets = set(msk) - reg.target_names
            if bad_targets:
                raise RegistryError(f"machine {name}: skills references unknown "
                                    f"target(s) {sorted(bad_targets)}")
            for tname, curation in msk.items():
                if not isinstance(curation, dict):
                    raise RegistryError(
                        f"machine {name}: skills.{tname} must be a mapping "
                        f"({{include: [...]}} or {{exclude: [...]}})")
                # A manual target stages a pile for a human to upload from; the choice already
                # happens at upload time, so curating the pile only removes options. Rejected
                # loudly for the reason the target-side rejection below gives — a list that
                # quietly does nothing is worse than one that fails.
                if is_manual_skill_target(reg.targets.get(tname) or {}):
                    raise RegistryError(
                        f"machine {name}: skills.{tname} cannot be curated — {tname} stages "
                        f"skills for you to upload by hand, so every compatible skill is "
                        f"offered and you choose at upload time. Remove the block.")
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
        # 7. agents (optional): curation of active agents for harnesses —
        #    `{include: [...] | exclude: [...]}`.
        mag = m.get("agents")
        if mag is not None:
            if not isinstance(mag, dict):
                raise RegistryError(f"machine {name}: 'agents' must be a mapping "
                                    f"({{include: [...]}} or {{exclude: [...]}})")
            inc, exc = mag.get("include"), mag.get("exclude")
            for label, lst in (("include", inc), ("exclude", exc)):
                if lst is None:
                    continue
                if not isinstance(lst, list):
                    raise RegistryError(
                        f"machine {name}: agents.{label} must be a list")
                bad = set(lst) - set(reg.agents)
                if bad:
                    raise RegistryError(
                        f"machine {name}: agents.{label} references "
                        f"unknown agent(s) {sorted(bad)}")
            both = set(inc or []) & set(exc or [])
            if both:
                raise RegistryError(
                    f"machine {name}: agents lists agent(s) in BOTH "
                    f"include and exclude: {sorted(both)}")
        # An `example: true` template is never deployed (compile skips it, deploy refuses it),
        # so an overlay agent needing a skill the template's store omits must not fail it.
        if not m.get("example"):
            from . import planner as plannermod
            for t in m.get("targets", []):
                tspec = reg.targets.get(t) or {}
                if not tspec.get("agents"):
                    continue
                t_agents = selected_agents(reg, m, target=t)
                if not t_agents:
                    continue
                sk_spec = tspec.get("skills", {})
                machine_skills = {s.name for s in plannermod._selected_skills(reg, sk_spec, m)}
                for aname in t_agents:
                    agent = reg.agents[aname]
                    for sk in agent.skills:
                        if sk not in machine_skills:
                            raise RegistryError(
                                f"machine {name}: selected agent {agent.name!r} requires "
                                f"skill {sk!r}, which is not deployed to this machine"
                            )
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

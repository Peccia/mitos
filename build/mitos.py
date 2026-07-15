#!/usr/bin/env python
"""Mitos CLI — the interactive, optional companion to the deterministic compiler.

Kept a SEPARATE entrypoint from build/compile.py (the Mitos boundary rule):
`init` prompts the user and scaffolds the private overlay; `connect` runs a workspace
connector and proposes a `kind: graph` candidate through the inbox valve. Neither is ever
imported by the compiler's deterministic verbs, and connector backend deps stay lazy.

Usage:
  python build/mitos.py init
  python build/mitos.py project add SLUG [--name NAME] [--document-store SERVER]
  python build/mitos.py connect --project SLUG [--folder-id ID [--recursive]] [--query TEXT] [--stage]
  python build/mitos.py connectors
  python build/mitos.py sync --machine NAME init|clone --hub URL [--branch B] [--ssh-key PATH]
  python build/mitos.py sync --machine NAME [all|pull|push|refresh|status] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "build"))


def _compiler_check(machine_name: str | None) -> None:
    """Print a notice when build/ is behind upstream, unless compiler_sync is disabled.

    Non-fatal: any error (no git, no network, offline) is swallowed silently so this
    never blocks init or sync. compiler_sync: false in the machine profile opts out."""
    try:
        from agentic import loader
        from agentic.sync.selfcheck import check_compiler
        reg = loader.load(REPO_ROOT)
        machine = reg.machines.get(machine_name or "") if machine_name else None
        sync_cfg = (machine or {}).get("sync") or {}
        if sync_cfg.get("compiler_sync") is False:
            return
        notice = check_compiler(REPO_ROOT)
        if notice:
            print(notice)
    except Exception:  # noqa: BLE001
        pass  # loader error, import error — never block the primary command


class _Abort(Exception):
    """The interactive prompt was cut short (stdin closed, or Ctrl-C/Ctrl-D) — unwind to a clean
    exit instead of a traceback. Raised before any file is written, so aborting changes nothing."""


def _ask(prompt: str) -> str:
    """`input()` that turns an EOF/interrupt into a clean abort rather than an EOFError traceback."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise _Abort from None


def _cmd_init(_args) -> int:
    """Set up the private overlay at registry/local/. Three paths: scaffold a fresh one, pull an
    overlay you already keep on a git hub, or finish around files already in registry/local/.
    None of them ever clobber existing overlay files."""
    _compiler_check(None)
    try:
        return _init_dispatch()
    except _Abort:
        print("\nsetup aborted — no changes made.", file=sys.stderr)
        return 130


def _init_dispatch() -> int:
    from agentic import init as initmod
    overlay = REPO_ROOT / "registry" / "local"
    has_local = overlay.is_dir() and any(p.name != ".git" for p in overlay.iterdir())
    print("Mitos setup — your private overlay lives at registry/local/ (gitignored).\n")
    if has_local:
        print(f"Note: an overlay already exists at {overlay.as_posix()} — your files there are "
              f"never overwritten.\n")
    print("How do you want to set up this machine's overlay?")
    print("  [1] Scaffold a fresh one (name, org template, backend)")
    print("  [2] Pull an overlay you already keep on a git hub (another machine's mitos-local)")
    print("  [3] Use the files already in registry/local/ as-is")
    default = "3" if has_local else "1"
    choice = _ask(f"Choice [{default}]: ") or default
    if choice == "2":
        return _init_pull_from_hub()
    if choice == "3":
        return _init_use_existing(overlay, has_local)
    return _init_scaffold_fresh(initmod, has_local)


def _init_scaffold_fresh(initmod, has_local: bool) -> int:
    templates = initmod.org_templates(REPO_ROOT)
    given = _ask("Given (first) name: ")
    family = _ask("Family (last) name: ")
    default_addr = given or family or "your name"
    address = _ask(f"How should the assistant address you? [{default_addr}]: ") \
        or given or family
    email = _ask("Your email: ")
    location = _ask("Location (optional): ")
    print(f"\nOrg routing (optional):")
    print(f"  blank (recommended) — dynamic multi-org router: all three domain orgs are")
    print(f"    available and the correct one activates per-project via each project's")
    print(f"    org: field. Best for mixed-domain work.")
    print(f"  a template name — locks the assistant to one domain's delegation chain")
    print(f"    for all project work, regardless of the project's org: field.")
    print(f"  Available templates: {', '.join(templates) or '(none found)'}")
    org_raw = _ask("Org template [blank=dynamic multi-org]: ").strip()
    org = org_raw if org_raw else None
    backend = _ask("Workspace backend [gws]: ") or "gws"
    try:
        written = initmod.scaffold_overlay(REPO_ROOT, given_name=given, family_name=family,
                                           address=address, email=email,
                                           location=location, org_template=org,
                                           backend=backend)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if written:
        print("\nCreated:")
        for p in written:
            print(f"  registry/{p}")
    if has_local:
        print("\nKept all your existing files; only the missing pieces above were added.")
    if backend and backend != "mock":
        print(f"\nNext: stand up the {backend} MCP server (see docs/connectors/), point the "
              f"`{backend}` entry in connections/servers.yaml at it, then run "
              f"`python build/mitos.py connect --project <slug>`.")
    return 0


def _init_pull_from_hub() -> int:
    """Onboard this machine from an overlay you already keep on a hub — a thin wrapper over
    `sync clone` so the existing files come down and the sync config is captured in one step."""
    from agentic.sync import SyncError, git_clone
    from agentic.sync.config import ensure_profile_sync_block
    hub = _ask("Hub URL (e.g. git@github.com:you/mitos-local.git): ")
    if not hub:
        print("error: a hub URL is required to pull", file=sys.stderr)
        return 2
    machine = _ask("A short name for THIS machine (e.g. windows-main): ")
    if not machine:
        print("error: a machine name is required", file=sys.stderr)
        return 2
    branch = _ask("Branch [main]: ") or "main"
    ssh_key = _ask("ssh key path (blank for your default / none): ") or None
    try:
        for line in git_clone(REPO_ROOT, machine, hub, branch=branch, ssh_key=ssh_key):
            print(line)
    except SyncError as e:
        print(f"sync error: {e}", file=sys.stderr)
        return 1
    print(ensure_profile_sync_block(REPO_ROOT, machine, hub, branch=branch, ssh_key=ssh_key))
    print("\nPulled your overlay from the hub. Finish with:")
    print("  python build/compile.py compile")
    print(f"  python build/compile.py deploy --machine {machine}")
    return 0


def _init_use_existing(overlay, has_local: bool) -> int:
    """Finish the install around files already in registry/local/ — nothing is overwritten.
    Optionally publish them to a hub (a thin wrapper over `sync init`)."""
    if not has_local:
        print(f"error: no overlay found at {overlay.as_posix()} — nothing to use. Pick [1] to "
              f"scaffold or [2] to pull from a hub.", file=sys.stderr)
        return 2
    print(f"Using the existing overlay at {overlay.as_posix()} as-is — nothing overwritten.")
    hub = _ask("\nPublish it to a sync hub now? Hub URL (blank to skip): ")
    if hub:
        from agentic.sync import SyncError, git_init
        from agentic.sync.config import ensure_profile_sync_block
        machine = _ask("A short name for THIS machine: ")
        if not machine:
            print("error: a machine name is required", file=sys.stderr)
            return 2
        branch = _ask("Branch [main]: ") or "main"
        ssh_key = _ask("ssh key path (blank for default / none): ") or None
        print(ensure_profile_sync_block(REPO_ROOT, machine, hub, branch=branch, ssh_key=ssh_key))
        try:
            for line in git_init(REPO_ROOT, machine, hub, branch=branch, ssh_key=ssh_key):
                print(line)
        except SyncError as e:
            print(f"sync error: {e}", file=sys.stderr)
            return 1
    print("\nDone. Compile + deploy with build/compile.py.")
    return 0


def _cmd_connect(args) -> int:
    """Stage 3 of the graph pipeline: map a project's documents into its knowledge graph.

    Backend-agnostic — the connector is resolved from the project's `document_store`
    (the MCP server you set up separately), so the same command works for any store. Pass
    `--backend mock` only to force the in-process demo connector.

    A project bound to MORE THAN ONE store (`document_store:` is a list) loops all of
    them, one enumeration + one candidate per store (`--store <name>` narrows to just
    one) — `--stage` loops the same way, one LISTING per store, all written into the same
    inbox/staging/<slug>.json (see build/agentic/staging.py). A project can also watch
    more than one scope WITHIN one store: re-staging the same store/folder/query/recursive
    combination replaces that listing, a different one appends alongside it. Overlapping
    watches are reported (`note: N documents also appear in watch ...`) but never blocked.

    If ``--project`` is omitted the command runs in *unassigned* mode: documents are staged
    to ``inbox/staging/unassigned.json`` without being bound to any project. Open the
    operator console to select documents and propose them to the project of your choice.
    Unassigned mode requires ``--stage``; proposing directly to the inbox without a project
    target is not supported."""
    from agentic import loader
    try:
        reg = loader.load(REPO_ROOT)
    except loader.RegistryError as e:
        print(f"registry error: {e}", file=sys.stderr)
        return 2

    slug = args.project  # may be None
    proj = reg.projects.get(slug) if slug else None

    # Unassigned mode: --project was omitted. Only --stage is supported here.
    if slug is None:
        if not args.stage:
            print("error: --project is required when not using --stage.\n"
                  "Unassigned staging (--stage without --project) writes "
                  "inbox/staging/unassigned.json so you can pick a project "
                  "in the console.", file=sys.stderr)
            return 2
        # Resolve the backend: explicit --backend wins, otherwise pick the first
        # project that has a document_store configured.
        if not args.backend:
            raw_store = next(
                (p.get("document_store") for p in reg.projects.values()
                 if p.get("document_store") and p.get("document_store") != "none"),
                None)
            if not raw_store:
                print("error: no project has a document_store configured.\n"
                      "Either add `document_store: <server>` to a project manifest or "
                      "pass --backend explicitly.", file=sys.stderr)
                return 2
        else:
            raw_store = None  # will use args.backend below
        slug = "unassigned"
    else:
        # Named project: must exist.
        if proj is None:
            print(f"error: unknown project {slug!r}; known: "
                  f"{', '.join(sorted(reg.projects)) or '(none)'}. Create one with "
                  f"`python build/mitos.py project add <slug>`.", file=sys.stderr)
            return 2
        # The most common stumble: a project with no store bound.
        if not args.backend and (not proj.get("document_store")
                                 or proj.get("document_store") == "none"):
            return _explain_missing_store(reg, slug)
        raw_store = proj.get("document_store")

    stores = loader.document_stores(raw_store)
    if args.store:
        if stores and args.store not in stores:
            print(f"error: --store {args.store!r} is not one of this project's "
                  f"document_store entries ({', '.join(stores)})", file=sys.stderr)
            return 2
        stores = [args.store]
    if args.backend or len(stores) <= 1:
        # Prefer the resolved project/unassigned store (for its exclude_folders config)
        # even under a --backend override; args.backend is only the last-resort fallback,
        # same priority order the single-store path always used.
        resolved_store = (stores[0] if stores else None) or args.backend
        return _connect_one(reg, args, slug, proj, resolved_store)

    # Multi-store: one enumeration + one candidate per store (prefer one candidate per
    # store — reuses the single-store shape verbatim, so each stays small and reviewable).
    exit_code = 0
    for store_val in stores:
        print(f"\n== store: {store_val} ==")
        rc = _connect_one(reg, args, slug, proj, store_val)
        exit_code = rc if rc != 0 else exit_code
    return exit_code


def _connect_one(reg, args, slug: str, proj: dict | None, resolved_store: str | None) -> int:
    """One connect pass against a single resolved store — the body `_cmd_connect` used to run
    once; now shared so a multi-store project can loop it. `resolved_store` is a plain
    server name (or None/args.backend), never a list."""
    from agentic.connectors import (ConnectorError, bootstrap_to_inbox, stage_listing,
                                     connector_for_store, get_connector)
    # Build the merged exclude_folders list: server-level ∪ project-level.
    servers = (reg.servers.get("servers") or {})
    server_cfg = servers.get(resolved_store) if resolved_store else {}
    server_excl = list(server_cfg.get("exclude_folders") or []) if server_cfg else []
    proj_excl = list(proj.get("exclude_folders") or []) if proj else []
    exclude_folders = list(dict.fromkeys(server_excl + proj_excl)) or None  # unique, ordered

    try:
        if args.backend:
            connector = get_connector(args.backend, root=REPO_ROOT)
        else:
            connector = connector_for_store(reg, resolved_store, root=REPO_ROOT)
        folder_id = args.folder_id
        if folder_id is None and not args.query:
            folder_id = _pick_folder(connector, exclude_folders=exclude_folders)
        recursive = bool(getattr(args, "recursive", False))
        if recursive and not folder_id:
            print("note: --recursive has no effect without a folder scope; listing the "
                  "store's default scope.", file=sys.stderr)
        if args.stage:
            result = stage_listing(reg, connector, slug,
                                   folder_id=folder_id, query=args.query,
                                   exclude_folders=exclude_folders, recursive=recursive,
                                   store=resolved_store or "")
            if result.get("ok"):
                print(f"staged {result['count']} document(s) to {result['path']}.")
                # Warn-only (see stage_listing/staging.overlapping_listings): an operator
                # watching two scopes that happen to share a document isn't an error —
                # both listings are written and either one's refresh keeps it visible.
                from agentic import staging as _staging
                for ov in result.get("overlap") or []:
                    print(f"note: {ov['count']} document(s) also appear in watch "
                          f"{_staging.scope_label(ov['scope'])!r} — refreshing either "
                          f"keeps them visible.", file=sys.stderr)
                print("Open `python build/compile.py review` → Knowledge Graph, pick the ones "
                      "you want, and Propose selected.")
                return 0
            print(f"error: {result.get('error')}", file=sys.stderr)
            return 1
        result = bootstrap_to_inbox(reg, connector, slug,
                                    folder_id=folder_id, query=args.query,
                                    exclude_folders=exclude_folders, recursive=recursive,
                                    store=resolved_store or "")
    except ConnectorError as e:
        print(f"connector error: {e}", file=sys.stderr)
        return 1
    except _Abort:
        print("\nconnect aborted — no changes made.", file=sys.stderr)
        return 130
    if not result.get("ok"):
        print(f"error: {result.get('error')}", file=sys.stderr)
        return 1
    print(f"proposed {result['registry_path']} as inbox candidate {result['id']}.")
    print("Review it with `python build/compile.py review`, then accept.")
    return 0


def _project_manifest_path(slug: str):
    """Where a project's manifest lives — overlay first (where user projects are created),
    then the core. Returns a Path or None."""
    from agentic import loader
    for base in (REPO_ROOT / "registry" / loader.LOCAL_OVERLAY / "projects",
                 REPO_ROOT / "registry" / "projects"):
        p = base / f"{slug}.yaml"
        if p.exists():
            return p
    return None


def _explain_missing_store(reg, slug: str) -> int:
    """Spell out, step by step, how to bind a document store — the #1 thing a new user hits.
    Names the available servers, the exact manifest file, and the exact line to add."""
    servers = sorted(reg.servers.get("servers") or {})
    mpath = _project_manifest_path(slug)
    rel = mpath.relative_to(REPO_ROOT).as_posix() if mpath else \
        f"registry/local/projects/{slug}.yaml"
    pick = servers[0] if servers else "<server>"
    e = sys.stderr
    print(f"project {slug!r} has no document store bound yet, so there is nothing to map.\n",
          file=e)
    print("A 'document store' is the MCP server that holds this project's files. The servers",
          file=e)
    print("Mitos knows about (defined in connections/servers.yaml) are:", file=e)
    print(f"    {', '.join(servers) or '(none defined yet)'}\n", file=e)
    print(f"Step 1 — open this project's manifest:", file=e)
    print(f"    {rel}", file=e)
    print(f"Step 2 — add this line (pick the server that holds the docs):", file=e)
    print(f"    document_store: {pick}", file=e)
    print(f"Step 3 — re-run:", file=e)
    print(f"    python build/mitos.py connect --project {slug}\n", file=e)
    print("Tip: `python build/mitos.py project add <slug> --document-store <server>` binds it "
          "when you first create a project. Use `document_store: none` only if the project "
          "genuinely has no document store.", file=e)
    return 2


def _pick_folder(connector, exclude_folders=None):
    """Offer the store's top-level folders as a numbered scope picker, returning the chosen
    folder id (or None for the default scope). Excluded folders are omitted from the list
    so the user cannot accidentally scope into one. Silent no-op — returns None — when
    stdin isn't interactive or the store exposes no folders, so scripted/headless runs are
    unaffected."""
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return None
    try:
        connector.authenticate()
        folders = connector.list_folders(exclude_folders=exclude_folders)
    except Exception:
        return None
    if not folders:
        return None
    print("\nScope the document mapping to a folder (blank = the store's default scope):")
    for i, f in enumerate(folders, 1):
        print(f"  [{i}] {f.get('name', '?')}")
    choice = _ask("Folder number [blank]: ")
    if not choice:
        return None
    try:
        idx = int(choice)
        if 1 <= idx <= len(folders):
            return folders[idx - 1].get("id")
    except ValueError:
        pass
    print("  (not one of the listed numbers — using the default scope)")
    return None


def _cmd_project(args) -> int:
    """Stage 1 of the graph pipeline: scaffold a project manifest in the overlay so there is a
    slug — and a `document_store` binding — to map documents against later. Offline, no network.
    The graph file itself is created when you accept the first `kind: graph` candidate."""
    from agentic import loader
    if args.action != "add":
        print(f"error: unknown project action {args.action!r}", file=sys.stderr)
        return 2
    slug = (args.slug or "").strip()
    if not slug or not all(c.isalnum() or c in "-_" for c in slug):
        print(f"error: invalid slug {slug!r} — use letters, digits, '-' or '_'",
              file=sys.stderr)
        return 2
    overlay = REPO_ROOT / "registry" / loader.LOCAL_OVERLAY
    manifest = overlay / "projects" / f"{slug}.yaml"
    if manifest.exists():
        print(f"error: project {slug!r} already exists at "
              f"registry/{loader.LOCAL_OVERLAY}/projects/{slug}.yaml", file=sys.stderr)
        return 2
    try:
        reg = loader.load(REPO_ROOT)
        stores = sorted(reg.servers.get("servers") or {})
        if slug in reg.projects:
            print(f"error: a project named {slug!r} already exists in the registry",
                  file=sys.stderr)
            return 2
    except loader.RegistryError:
        stores = []
    try:
        store = args.document_store
        if store is None:
            print("A document store is the MCP server that holds this project's files; binding "
                  "one lets\nMitos map them into the knowledge graph later "
                  "(`connect`). You can also set this\nlater by editing the manifest.")
            print(f"  available servers (connections/servers.yaml): "
                  f"{', '.join(stores) or '(none defined)'}")
            print("  or 'none' if this project has no document store")
            store = _ask("document_store [none]: ") or "none"
        name = args.name or _ask(f"Project display name [{slug}]: ") or slug
    except _Abort:
        print("\nproject add aborted — no changes made.", file=sys.stderr)
        return 130
    if store != "none" and stores and store not in stores:
        print(f"error: document_store {store!r} is not a known server; known: "
              f"{', '.join(stores)}", file=sys.stderr)
        return 2
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(_project_manifest_yaml(slug, name, store), encoding="utf-8")
    print(f"created registry/{loader.LOCAL_OVERLAY}/projects/{slug}.yaml")
    if store != "none":
        print("\nNext: map its documents into the knowledge graph (Stage 3):")
        print(f"  python build/mitos.py connect --project {slug}")
    else:
        print(f"\nSet `document_store:` in the manifest to a server, then "
              f"`python build/mitos.py connect --project {slug}`.")
    return 0


def _project_manifest_yaml(slug: str, name: str, store: str) -> str:
    return (f"# Project manifest — created by `mitos project add`. Fill in the rest as the\n"
            f"# project takes shape (context partials, local_path, skills/agents).\n"
            f"name: {name}\n"
            f"slug: {slug}\n"
            f"stage: ideation          # ideation | speccing | build | maintain\n"
            f"repo: \"\"\n"
            f"document_store: {store}   # MCP server (connections/servers.yaml) backing graph "
            f"init; 'none' = unmapped\n"
            f"# context:\n"
            f"#   assistant: registry/local/context/projects/{slug}.md\n")


def _cmd_connectors(_args) -> int:
    from agentic.connectors import available
    print("available connectors:", ", ".join(available()))
    return 0


def _load_machine_yaml(repo_root: Path, machine_name: str) -> dict | None:
    """Read one machine's yaml directly, bypassing full registry validation.

    Used as a fallback when loader.load() fails (e.g. stale skill targets on a machine
    that hasn't pulled the latest overlay yet). Checks registry/local/machines/ first
    (overlay wins), then registry/machines/.
    """
    import yaml as _yaml
    for machines_dir in (
        repo_root / "registry" / "local" / "machines",
        repo_root / "registry" / "machines",
    ):
        if not machines_dir.is_dir():
            continue
        for yf in machines_dir.glob("*.yaml"):
            try:
                data = _yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if data.get("name") == machine_name:
                return data
    return None


def _cmd_sync(args) -> int:
    """Set up and run git-only overlay sync. `init`/`clone` make the overlay repo on the first /
    subsequent machines (and install the auto-deploy hook); the default flow reconciles it with
    its hub: pull --rebase -> deploy -> push, stopping on conflict. The hub is `sync.git.hub` in
    the machine profile — any git URL (a self-hosted server or a private GitHub repo)."""
    _compiler_check(args.machine)
    from agentic import loader
    from agentic.sync import SyncError, git_clone, git_init, git_status, git_sync
    try:
        reg = loader.load(REPO_ROOT)
    except loader.RegistryError as e:
        # init/clone need a valid registry (the machine profile must be present in the overlay
        # they are about to set up). For all other actions the pull itself may fix the stale
        # overlay — fall back to reading the machine yaml directly so sync isn't chicken-and-egg.
        if args.action in ("init", "clone"):
            print(f"registry error: {e}", file=sys.stderr)
            return 2
        print(f"registry warning: {e}", file=sys.stderr)
        print("registry validation failed — attempting sync with raw machine config "
              "(pull may fix the overlay)", file=sys.stderr)
        reg = None

    # init/clone bootstrap the repo, so the machine's profile (which may live *in* the overlay
    # being set up) need not exist yet — the hub comes from --hub, not the sync: block.
    if args.action in ("init", "clone"):
        if not args.hub:
            print(f"error: `mitos sync {args.action}` needs --hub <git-url|path>",
                  file=sys.stderr)
            return 2
        from agentic.sync.config import ensure_profile_sync_block
        # Flags win; otherwise inherit anything already in the machine's profile (init often runs
        # before the profile exists, so the flags are the reliable path).
        pgit = ((reg.machines.get(args.machine) or {}).get("sync") or {}).get("git") or {}
        ssh_key = args.ssh_key or pgit.get("ssh_key")
        remote = args.remote or pgit.get("remote") or "origin"
        branch = args.branch or pgit.get("branch") or "main"
        # init: capture into the profile BEFORE the repo's initial commit, so the sync config is
        # tracked from the first push. clone: after the cloned tree lands, then prompt to commit.
        captured = None
        if args.action == "init":
            captured = ensure_profile_sync_block(REPO_ROOT, args.machine, args.hub,
                                                 remote=remote, branch=branch, ssh_key=ssh_key)
        fn = git_init if args.action == "init" else git_clone
        try:
            for line in fn(REPO_ROOT, args.machine, args.hub,
                           remote=remote, branch=branch, ssh_key=ssh_key):
                print(line)
        except SyncError as e:
            print(f"sync error: {e}", file=sys.stderr)
            return 1
        if args.action == "clone":
            captured = ensure_profile_sync_block(REPO_ROOT, args.machine, args.hub,
                                                 remote=remote, branch=branch, ssh_key=ssh_key)
        if captured:
            print(captured)
            if args.action == "clone" and captured.startswith("captured"):
                print("commit it: cd registry/local && git add -A && "
                      "git commit -m 'configure sync' && git push")
        return 0

    machine = (reg.machines.get(args.machine) if reg is not None
               else _load_machine_yaml(REPO_ROOT, args.machine))
    if machine is None:
        known = (f"{', '.join(sorted(reg.machines))}" if reg is not None
                 else "(registry failed to load — check machine yaml files)")
        print(f"error: unknown machine {args.machine!r}; known: {known}", file=sys.stderr)
        return 2
    cfg = machine.get("sync")
    if not cfg or not (cfg.get("git") or {}).get("hub"):
        print(f"error: machine {args.machine!r} has no sync.git.hub configured — add a "
              f"sync: block to its profile (see docs/lan-sync.md)", file=sys.stderr)
        return 2

    if args.action == "status":
        try:
            for line in git_status(REPO_ROOT, cfg, args.machine):
                print(line)
        except SyncError as e:
            print(f"sync error: {e}", file=sys.stderr)
            return 1
        return 0

    from agentic import commands

    def _deploy(m: str) -> int:
        # Always reload the registry fresh so deploy uses the just-pulled overlay, not the
        # pre-pull snapshot that may have been invalid (stale skill targets, etc.). If the
        # registry is STILL invalid here, the pull didn't carry the fix (or the error is a
        # genuine corruption no pull resolves) — fail loudly so push doesn't follow a bad deploy.
        try:
            fresh_reg = loader.load(REPO_ROOT)
        except loader.RegistryError as err:
            print(f"registry still invalid, deploy aborted: {err}", file=sys.stderr)
            return 1
        return commands.cmd_deploy(fresh_reg, m, False, False)

    try:
        for line in git_sync(REPO_ROOT, args.machine, cfg, action=args.action,
                             dry_run=args.dry_run,
                             deploy=_deploy):
            print(line)
    except SyncError as e:
        print(f"sync error: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="mitos.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="scaffold the private overlay at registry/local/")
    pp = sub.add_parser("project", help="scaffold a project manifest (Stage 1 of graph init)")
    pp.add_argument("action", choices=["add"], help="add = create a new project manifest")
    pp.add_argument("slug", help="the project slug (letters, digits, '-' or '_')")
    pp.add_argument("--name", default=None, help="display name (defaults to the slug)")
    pp.add_argument("--document-store", default=None,
                    help="MCP server (connections/servers.yaml) backing graph init, or 'none'")
    pc = sub.add_parser("connect",
                        help="map a project's docs into its knowledge graph (Stage 3)")
    pc.add_argument("--project", default=None,
                    help="project slug to map (omit to stage without assigning to a project)")
    pc.add_argument("--backend", default=None,
                    help="force the in-process demo connector (mock); default: resolved from "
                         "the project's document_store (an MCP server)")
    pc.add_argument("--folder-id", default=None)
    pc.add_argument("--recursive", action="store_true",
                    help="with --folder-id, include files in all nested subfolders "
                         "(transitively), not just the folder's immediate children")
    pc.add_argument("--query", default=None)
    pc.add_argument("--stage", action="store_true",
                    help="discover the scope and write inbox/staging/<slug>.json for the "
                         "console to curate (instead of proposing every file at once). "
                         "Required when --project is omitted.")
    pc.add_argument("--store", default=None,
                    help="which of the project's document_store entries to use — only "
                         "needed when the project binds more than one store; omit to loop "
                         "all of them (one candidate per store; not supported with --stage)")
    sub.add_parser("connectors", help="list available workspace connectors")
    ps = sub.add_parser("sync", help="set up and run git-only overlay sync")
    ps.add_argument("--machine", required=True)
    ps.add_argument("action", nargs="?", default="all",
                    choices=["all", "pull", "push", "refresh", "init", "clone", "status"],
                    help="all = pull→deploy→push (default); pull = pull+deploy; push = push; "
                         "refresh = deploy only; init = make the overlay repo (needs --hub); "
                         "clone = onboard this machine from the hub (needs --hub); "
                         "status = report ahead/behind vs the hub")
    ps.add_argument("--hub", default=None,
                    help="git remote URL or path for `init`/`clone` (self-hosted or private repo)")
    ps.add_argument("--ssh-key", default=None,
                    help="path to the private key for an ssh hub (pins the overlay repo's "
                         "core.sshCommand; or set sync.git.ssh_key in the machine profile)")
    ps.add_argument("--branch", default=None,
                    help="branch to sync on, for `init`/`clone` (default: main)")
    ps.add_argument("--remote", default=None,
                    help="git remote name, for `init`/`clone` (default: origin)")
    ps.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "init":
        return _cmd_init(args)
    if args.cmd == "project":
        return _cmd_project(args)
    if args.cmd == "connect":
        return _cmd_connect(args)
    if args.cmd == "connectors":
        return _cmd_connectors(args)
    if args.cmd == "sync":
        return _cmd_sync(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

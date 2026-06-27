# Syncing your private context across machines

Mitos keeps your machines in sync with **git**. Your private overlay (`registry/local/`) is its
own git repository, synced to a **hub** you choose — any git remote: a server you host, a bare
repo on a box/NAS, or a private GitHub repo. (`inbox/` proposals live within the overlay repo itself.)
Secrets in `.local/` are never synced.

## Running these commands — what `mitos` means

Until the packaged CLI is installed, **`mitos` is shorthand** for your venv interpreter + the
script:

| Platform | `mitos` = |
|---|---|
| Windows (PowerShell) | `build\.venv\Scripts\python.exe build\mitos.py` |
| Linux / macOS | `build/.venv/bin/python build/mitos.py` |

So `mitos sync --machine main` is `build/.venv/bin/python build/mitos.py sync --machine main`.

## What `mitos sync` does

Every machine is a peer of the same hub. `mitos sync --machine <this-machine>` runs:

1. `git pull --rebase` the overlay — fetch peers' changes, replay yours on top.
2. **On conflict: stop.** It reports the conflicted files and leaves them for you to resolve
   (`git rebase --continue` / `--abort`). It never auto-resolves and never forces.
3. `deploy --machine <this-machine>` — materialize the merged overlay into this host's harnesses.
4. `git push` — publish your commits to the hub.

Sub-commands: `push` / `pull` / `refresh` (deploy only) / `status` (ahead/behind vs the hub);
`--dry-run` previews the pull/push counts without changing anything. Commit your overlay edits
before syncing — a dirty tree is refused:
```bash
cd registry/local
git add -A
git commit -m "describe what changed"
cd ../..
mitos sync --machine <this-machine> push
```

## The hub — any git remote

| Hub | Example URL | Notes |
|---|---|---|
| Self-hosted git server (Gitea / GitLab / plain git) | `ssh://you@gitserver/mitos-local.git` | own your data; recommended |
| Bare repo on an always-on box / NAS | `ssh://you@box/srv/mitos-local.git` or `//NAS/git/mitos-local.git` | minimal; nothing to install |
| Private GitHub / GitLab.com repo | `git@github.com:you/mitos-local.git` | easiest; hosted by a third party |

Auth is git's own (an SSH key or the credential helper); Mitos stores no credentials. If your hub
is reached over **ssh** and the right key isn't your default, point Mitos at it — either
`--ssh-key <path>` on `init`/`clone`, or `sync.git.ssh_key` in the machine profile. Mitos pins it
as the overlay repo's `core.sshCommand` (with `IdentitiesOnly=yes`), so every git operation on the
overlay — the sync flow, the auto-deploy pull, even a bare cron `git pull` — uses that one key.

The key is resolved to an **absolute path**: a bare name like `id_github` is looked up in
`~/.ssh/`, a `~/…` path is expanded, and a relative path resolves from where you ran the command.
(This matters because git runs `core.sshCommand` from its own working directory, so a relative
`-i` would otherwise point at the wrong place.) If the file isn't there, `init`/`clone` stop with a
clear "ssh key not found at …" instead of a cryptic `Permission denied (publickey)`.

## Setup — `mitos sync` does it for you

**On your first machine** (`init` makes the overlay a repo, commits it, installs the auto-deploy
hook, records this machine's name, and pushes):

```bash
mitos sync --machine <this-machine> init --hub <hub-url> [--branch <b>] [--ssh-key <path>]
```

- **It captures the config for you.** `init` writes the `sync:` block (hub, branch, and ssh key if
  given) straight into `registry/local/machines/<this-machine>.yaml`, so there's no profile to
  hand-edit. (If that profile doesn't exist yet, it prints the exact block to paste once you create
  it.)
- If `--hub` is a **local path** it can reach (a directory, a mounted share, `file://…`) and the
  bare repo doesn't exist yet, `init` creates it for you (`git init --bare`).
- For a **hosted provider** (GitHub/GitLab.com) or an **ssh** server, create the empty **private**
  repo (or `git init --bare` on the box) **first**, then point `--hub` at it.
- `--branch <b>` syncs on a branch other than `main`; `--remote <name>` names the remote
  (default `origin`).
- `--ssh-key <path>` if the hub is ssh and needs a specific private key (e.g. a GitHub deploy
  key). It is pinned to the overlay repo, not stored by Mitos.

**On every other machine** (`clone` pulls the overlay into place, installs the hook, records this
machine's name, and captures the same `sync:` block into this machine's profile; an existing
`registry/local/` is moved aside first, never clobbered):

```bash
mitos sync --machine <this-machine> clone --hub <hub-url> [--branch <b>] [--ssh-key <path>]
```

The resulting `sync:` block looks like this — what `init`/`clone` write, and what `mitos sync`
reads on every run:

```yaml
sync:
  git:
    hub: "<hub-url>"            # the overlay repo's origin (must match)
    branch: "main"             # the branch this machine syncs
    # remote: "origin"         # only when not the default
    # ssh_key: "~/.ssh/mitos"  # a specific private key, for an ssh hub
```

From then on, `mitos sync --machine <that-machine>` keeps it in step, and
`mitos sync --machine <that-machine> status` shows how far ahead/behind the hub it is.

Auto-deploy: after a sync pulls new overlay content, the installed `post-merge` hook re-runs
`deploy` for this machine, so its harnesses update without a second command. (It no-ops when the
overlay didn't change and never force-deploys.)

## What never leaves your control

- `registry/local/` (including `inbox/` inside it) is gitignored from the public Mitos repo
  and lives only on your hub.
- Secrets in `.local/` are never synced.
- `mitos sync` never force-pushes, and refuses to sync if the overlay's remote isn't your
  configured hub.

# Google Workspace MCP Server — Docker Guide

This guide describes how to run the [Google Workspace MCP server](https://github.com/taylorwilsdon/google_workspace_mcp)
(taylorwilsdon's upstream project) locally in a Docker container using your personal
`@gmail.com` account. This is the **server** the `gws` entry in `connections/servers.yaml`
points at — an external tool, **not** part of the Mitos repo.

> **Credential note.** The `client_secret.json` below is the **docker server's** OAuth
> credential — it lives with the server, never inside Mitos. Mitos itself holds no Google
> credentials: it reaches Drive only by calling this running MCP server.

---

## Step 1: Save your Google Cloud OAuth Credentials

1. Go to your Google Cloud Console project (`agentic`).
2. Download your OAuth 2.0 Client credentials JSON file.
3. Save it as **`client_secret.json`** in your Mitos checkout's `.local/` directory (gitignored), e.g. `.local/client_secret.json`.

---

## Step 2: Clone the upstream server, then build and start the container

The server lives in its **own upstream repository** — clone it separately (it is not a
subfolder of your Mitos checkout):

```bash
git clone https://github.com/taylorwilsdon/google_workspace_mcp
cd google_workspace_mcp
docker compose up --build -d
```

This builds the Docker image and starts the server in the background. Point the container
at the `client_secret.json` and `.local/gws.env` you prepared, per the upstream README.

---

## Step 3: Connect your AI client

Any MCP-compatible client can connect to the running server:

* **Endpoint**: `http://localhost:8000/mcp`
* **Transport**: `streamable-http` or `http`

For Mitos-managed tools you do **not** copy any config by hand: `deploy --machine <name>`
renders the `gws` server into each tool's native MCP config (for Antigravity, a surgical
`json_merge` into `~/.gemini/config`; for Hermes, a `yaml_merge` into its `config.yaml`).
Run a deploy and the wiring lands automatically. Only connect manually if you're using a
client Mitos doesn't manage.

---

## Step 4: Complete the Google OAuth flow

> **MUST be done from a browser that can reach `localhost:8000` on the server machine.**
>
> The server's OAuth callback is hard-coded to `http://localhost:8000/oauth2callback`. If you
> are completing this step from a different PC (e.g. the server is on a headless linux-box),
> use an SSH tunnel so the redirect resolves correctly:
> ```bash
> ssh -L 8000:localhost:8000 <user>@<server-ip>
> ```
> Then open the Authorization URL in your local browser — the `localhost:8000` redirect will
> tunnel back to the server.

Because this is a personal `@gmail.com` account running on a local container, you need to
trigger the initial login flow:

1. View the container logs to get the authorization URL:
   ```bash
   docker compose logs gws_mcp
   ```

2. Look for a section in the logs that looks like this:
   ```text
   **ACTION REQUIRED: Google Authentication Needed for Google Calendar**
   1. Open this URL in your browser to authorize access:
      Authorization URL: https://accounts.google.com/o/oauth2/auth?...
   ```

3. **Copy the URL** and paste it into your browser.
4. Log in with your **Google account** (the `USER_GOOGLE_EMAIL` you configured).
5. **IMPORTANT**: On the permissions screen, grant **all requested scopes** — do not uncheck
   any boxes before clicking **Continue**. For knowledge-graph init specifically, the server
   needs at minimum:
   - **Google Drive** — "See and download all your Google Drive files" (`drive.readonly`)
     — required for `search_drive_files` to list and return file metadata.
   - **Google Drive files** — "See, edit, create, and delete only the specific Google Drive
     files you use with this app" (`drive.file`) — included in the upstream server's full
     scope request.

   The upstream server requests all Workspace scopes at once (Calendar, Gmail, Drive, Docs,
   etc.). If you uncheck Drive, `search_drive_files` will return an authorization error and
   `mitos connect` will fail.
6. Once you click Continue, the page will redirect to `http://localhost:8000/oauth2callback`.
7. You should see a success message in the browser. The container will automatically catch
   the callback code, exchange it for a token, and save it in a persistent Docker volume
   (`store_creds`). You will not need to authenticate again unless your token is revoked.

---

## Step 5: Verify the server is running

You can check the health of the running HTTP server:

* Open your browser and go to `http://localhost:8000/health` (it should return a JSON health status).
* You can query the list of available tools by sending a POST request or using the CLI.

---

## Using this server for knowledge-graph init

Once the server is running and OAuth is complete, Mitos can index a project's documents into
its knowledge graph by **reusing this server** — no second OAuth, no extra credentials.

**Prerequisite — install `requests` on the machine running `mitos connect`:**
```bash
build/.venv/bin/python -m pip install requests   # Linux/macOS venv
# build\.venv\Scripts\python.exe -m pip install requests   # Windows venv
```
`requests` is an optional dep (kept out of `requirements.txt` to keep the compiler lean) that
the MCP connector lazy-imports. The connector raises a clear error if it is missing.

**`mitos connect` must run on the same machine as the MCP server** (or any machine that can
reach `http://localhost:8000/mcp`). The server holds the OAuth token — callers just POST to
the MCP endpoint and the server authenticates to Google on their behalf. If the server is on
a remote machine, point `url:` in `connections/servers.yaml` (or a
`registry/local/connections/servers.yaml` field-level override) at its reachable address.

**Staged discovery — enumerate on the server machine, review on any PC:**

Everything travels on **one channel** — your private mitos-local overlay repo. `inbox/` now
lives inside `registry/local/inbox/`, so `mitos sync` carries the staging file along with
project manifests and identity. No changes to the public-track repo are needed.

1. On the machine running the GWS server, create the project manifest and push the overlay:
   ```bash
   python build/mitos.py project add <slug> --document-store gws
   cd registry/local
   git add -A
   git commit -m "add <slug> project"
   cd ../..
   python build/mitos.py sync --machine <this-machine> push
   ```
   On your review PC, pull the overlay so the project is known there too:
   ```bash
   python build/mitos.py sync --machine <review-machine> pull
   ```

2. Still on the server machine, stage the Drive file listing:
   ```bash
   python build/mitos.py connect --project <slug> --stage
   ```
   *Note: You can omit `--project <slug>` to stage all documents without assigning them to a project first (this writes to `unassigned.json`):*
   ```bash
   python build/mitos.py connect --stage
   ```
   This writes `registry/local/inbox/staging/<slug>.json` (or `unassigned.json`) — the Drive file list with IDs,
   names, dates, and web links. It does **not** propose anything yet.

3. Push the staging file via the overlay so the review PC can pull it:
   ```bash
   cd registry/local
   git add -A
   git commit -m "stage: <slug> document listing"
   cd ../..
   python build/mitos.py sync --machine <this-machine> push
   ```
   On your review PC:
   ```bash
   python build/mitos.py sync --machine <review-machine> pull
   ```

4. On the review PC, open the operator console and curate:
   ```bash
   python build/compile.py review
   ```
   → Knowledge Graph tab → select the project → tick the documents you want → **Propose
   selected** → accept the inbox candidate → `registry/graph/<slug>.jsonld` is written.

Alternatively, skip `--stage` to propose all enumerated files at once:
```bash
python build/mitos.py connect --project <slug>
```

To map a folder **and everything nested inside it**, add `--folder-id <id> --recursive` (works
with or without `--stage`):
```bash
python build/mitos.py connect --project <slug> --folder-id <id> --recursive
```

This MCP server is the only way Mitos reaches Google Workspace — it holds no Google credentials
of its own. Run the server (Steps 1–5 above) before mapping any Drive folder.

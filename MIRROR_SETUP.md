# Setting up the live wiki mirror on GitHub

You provide nothing secret — the wiki API is public. Here is the whole process in plain steps.

## One-time setup
1. Create a free GitHub account (if you don't have one) and a new **repository** (call it `loe-engine`).
2. Upload the contents of this `v2/` folder into the repo.
3. Move the workflow file into the special folder GitHub looks for:
   - rename `.github-workflow-loe-mirror.yml` to `.github/workflows/loe-mirror.yml`
   - (that `.github/workflows/` path is the only place GitHub runs scheduled jobs from)
4. In the repo: **Settings -> Actions -> General -> Workflow permissions -> Read and write**. This lets
   the daily job commit refreshed data back.
5. (Optional, to publish the app) **Settings -> Pages -> Source: GitHub Actions**.

## What happens after that
- Every day at 06:00 UTC, GitHub runs `mirror_fetch.py`. It asks the wiki for the current revision
  number of each page we care about, downloads ONLY the ones that changed, and commits them.
- If anything changed, it re-runs the whole engine and republishes the app. If nothing changed
  (most days), it does almost nothing and costs almost nothing.
- You can also hit **Actions -> LOE Mirror Sync -> Run workflow** to force a refresh any time.

## The first run
The very first sync downloads everything in scope (a few hundred data pages) and builds the manifest.
Every run after that is incremental. To watch it work the first time, use the manual "Run workflow"
button and read the log — it prints "CHANGED or NEW: N" and "mirror updated: N pages fetched".

## What I may still need from you
- Nothing to start — the API is public and the fetcher already targets the correct wiki.
- IF the wiki ever rate-limits or requires a contact string, we add a real contact to the User-Agent
  in `mirror_fetch.py` (currently a placeholder github URL). Easy change if it comes up.

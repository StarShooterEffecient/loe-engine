# Putting the LOE Engine on GitHub — complete walkthrough

Everything you'll see on each screen, and what to pick. No coding. ~15 minutes.

--------------------------------------------------------------------------------
## Before you start
Unzip `LOE_v2.zip`. You'll get a folder named `v2` full of files. Keep that folder open
in a window — you'll drag from it. It already contains everything GitHub needs:
  - README.md ............ the project's front page (already written)
  - LICENSE .............. MIT license (already written; see "License" below)
  - .gitignore ........... tells GitHub which junk files to ignore (already written)
  - .github-workflow-loe-mirror.yml ... the daily auto-sync (you'll move this in Step 5)
  - all the .py engine files

Because these are already included, you do NOT need GitHub to generate a README, .gitignore,
or license for you. When the setup screen offers them, you'll SKIP them (details below) so
they don't collide with the ones you're uploading.

--------------------------------------------------------------------------------
## Step 1 — Create a free GitHub account
Go to github.com -> Sign up -> verify your email. Done.

--------------------------------------------------------------------------------
## Step 2 — Create the repository
Top-right **+** -> **New repository**. You'll see these fields:

  - Repository name:  loe-engine   (or anything you like)
  - Description:      optional, e.g. "Meta-blind League build optimizer"
  - Public / Private: choose **Public**
       (free GitHub Actions minutes are unlimited on public repos; on private they're capped.
        Public is also fine because there are no secrets in this project.)

  Then a section titled **"Initialize this repository with:"**  -- IMPORTANT:
  - [ ] Add a README file .............. LEAVE UNCHECKED (we're uploading our own)
  - [ ] Add .gitignore ................. LEAVE UNCHECKED / "None" (we're uploading our own)
  - [ ] Choose a license ............... LEAVE AS "None" (we're uploading our own MIT LICENSE)

  Why leave them all off: if GitHub creates its own README/.gitignore/LICENSE, they clash with
  the ones already in your `v2` folder and you'd have to resolve duplicates. Starting EMPTY and
  uploading ours is the clean path.

  Click **Create repository**.

--------------------------------------------------------------------------------
## Step 3 — Upload the files
On the new empty repo page, find the link **"uploading an existing file"** (or
**Add file -> Upload files**). Open your `v2` folder, select EVERYTHING inside it, and drag it
all onto the page. Wait for the uploads to finish.

  Note: files that start with a dot (.gitignore, .github-workflow-...) sometimes look hidden in
  your file browser. On Windows enable "Hidden items" in the View menu; on Mac press
  Cmd+Shift+. (period) to reveal them, so they get uploaded too.

Scroll down, leave the commit message as-is, click **Commit changes**.

--------------------------------------------------------------------------------
## Step 4 — (You can ignore branches, tags, releases, and templates)
GitHub will mention "main branch", and offer Tags, Releases, and repository Templates elsewhere.
You need NONE of them for this. Default branch "main" is correct. Ignore the rest.

--------------------------------------------------------------------------------
## Step 5 — Move the workflow file into the special folder
GitHub only runs scheduled jobs from a folder called `.github/workflows/`. Right now the file is
named `.github-workflow-loe-mirror.yml` at the top level. Rename it:

  1. Click that file in your repo.
  2. Click the pencil (Edit) icon, top-right of the file view.
  3. At the very top, the filename is shown in an editable box. Change it to exactly:

         .github/workflows/loe-mirror.yml

     (Typing "/" creates folders automatically. So this both MOVES and RENAMES it.)
  4. Click **Commit changes**.

--------------------------------------------------------------------------------
## Step 6 — Let the daily job update the repo
**Settings** (top of repo) -> **Actions** -> **General** -> scroll to **Workflow permissions**
-> select **Read and write permissions** -> **Save**.
(Without this, the daily sync can fetch data but can't commit the refreshed files back.)

--------------------------------------------------------------------------------
## Step 7 — (Optional) publish the app as a web page
**Settings** -> **Pages** -> under "Source" choose **GitHub Actions**. After the next successful
run, your app is live at:  https://YOURNAME.github.io/loe-engine/

--------------------------------------------------------------------------------
## Step 8 — Run it for the first time
**Actions** tab -> click **"LOE Mirror Sync & Rebuild"** on the left ->
**Run workflow** button -> green **Run workflow**.
Click into the running job to watch the log.

  WHAT TO EXPECT: this is the FIRST time the fetcher talks to the live wiki (it couldn't be tested
  against the real wiki where it was built). The log prints lines like
     "wiki reports N pages in scope"
     "CHANGED or NEW: N"
     "mirror updated: N pages fetched"
  If instead you see an error (a 403, a rate-limit message, or an odd API response), that's normal
  for a first live run -- COPY THE LOG and bring it back to me. I'll read the exact error and fix
  the fetcher. This back-and-forth is expected, not a failure.

--------------------------------------------------------------------------------
## What you do NOT need
  - A repository template ...... no; you're uploading a finished project.
  - GitHub Desktop / git CLI ... no; the web uploader is enough.
  - Paid anything ............. no; public repo + Actions + Pages are all free here.
  - Secrets / API keys ........ no; the wiki API is public.
  - Node.js / build tools ..... no; it's plain Python that runs on GitHub's machines.

## One thing that MIGHT come up later
Some wikis ask automated tools to include a real contact in their "User-Agent" so they can reach
you. The fetcher has a placeholder. If the wiki rate-limits or asks, give me an email or your
GitHub URL and I'll bake it in — a two-second change to mirror_fetch.py.

# Reviewing code on GitHub

Copy [the example](../examples/devpilot-review.yml) into a repository as `.github/workflows/devpilot-review.yml` on its default branch. The hosted onboarding service can open this setup change for new repositories as described in [the architecture guide](architecture.md). For a manual install, replace both `@main` action references with the full commit SHA of the DevPilot release you reviewed.

1. Add `GEMINI_API_KEY` as an Actions repository or eligible organization secret to run Gemini. Without it, the example uses the offline pattern checker. Its review summary identifies the mock provider.
2. Under **Settings → Actions → General → Workflow permissions**, enable **Allow GitHub Actions to create and approve pull requests**. DevPilot uses this permission to open a fix PR. A repository or organization policy that prevents Actions from opening PRs will block that step.
3. Open a pull request or push code. DevPilot posts findings directly on the PR or commit. When its review produces editable fixes, the comment includes a run link, run ID and proposal SHA-256.
4. Open the run and download the **devpilot-proposal** artifact. Read `preview.diff` to see every proposed change. Ignoring the proposal leaves the branch as it is.
5. To approve, go to **Actions → DevPilot review → Run workflow**, select the repository's **default branch**, choose **approve**, and paste the review run ID and full SHA-256. The resulting fix PR targets the reviewed branch. Review and merge it through the repository's usual process.

## What each event reviews

| Event | Review scope |
|---|---|
| Pull request opened, updated, reopened, or marked ready | The code diff between the PR's base and head revisions. Findings appear inline where GitHub supports them. Fork PRs can receive feedback. Fix PRs require a same-repository source branch. |
| Branch push | The pushed commit range. A new non-default branch starts with the head commit's changes. A merge from an already-reviewed PR skips the duplicate commit review. |
| First push to the default branch, or first installation of the workflow on that branch | A baseline review of existing source. Coverage appears in the review summary. |
| Manual **baseline** run on the default branch | The same snapshot review, even when no code has changed. |

Baseline reviews consider regular source files in sorted path order, up to 50 files, 80 blob reads and 50,000 diff characters. Oversized or non-UTF-8 files are skipped. The review reports how much of the returned tree it covered. Source changes on DevPilot's own fix and onboarding branches do not trigger another proposal.

## What approval authorizes

A proposal can include up to eight source files with verified findings. DevPilot prepares the code once and records the proposed content alongside the original file's Git blob ID. Hidden paths such as `.github`, symlinks and submodules are excluded. Some findings need a human fix and have no downloadable edit.

Only a repository collaborator with write access can apply a proposal. Approval checks the workflow run, repository, reviewed commit, each original blob and the full patch digest. If the source branch moves, run a fresh review. Artifacts expire after seven days. Repeating the same approval reuses the existing fix PR. DevPilot does not merge the fix.

The legacy Java webhook gateway posts PR feedback independently. For these downloadable proposals and fix PRs, install the Actions workflow. Use one review integration per repository to avoid duplicate comments.

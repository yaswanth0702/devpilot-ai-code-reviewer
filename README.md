# DevPilot: AI Code Review Agent

DevPilot reviews changed code, explains suspected bugs, and prepares a diff you can approve. Use the browser for a single source file, the CLI for a local working copy, or GitHub Actions for pull requests and pushes.

| Where you work | How to review | What approval does |
|---|---|---|
| Browser | Paste code or open a UTF-8 source file. Review the findings and ask follow-up questions. | Applies the displayed change in the editor, then lets you download the corrected file. |
| Terminal | Run `devpilot review` for a Git diff or `devpilot check FILE --apply` for one file. | Typing `yes` at the file prompt replaces the reviewed source file after a fresh content check. |
| GitHub Actions | A configured workflow reviews changed lines and posts findings. When an edit is available, the review links to its patch. | A repository writer approves the identified proposal and DevPilot opens a fix pull request for the reviewed branch. |
| Self-hosted Java gateway | A signed GitHub pull request webhook queues a review in the database. | This integration posts review comments. Use the Actions workflow for approved fix PRs. |

Gemini, Claude, GPT and OpenAI-compatible services can power reviews. The offline demo recognizes a small set of patterns and lets you try the approval flow without an API key.

---

## Architecture

The Python agent turns source changes into a diff, reads relevant files, searches for context, and returns line-level findings. Its verifier checks the location, confidence and duplication of those findings. The browser, CLI and GitHub workflow share this review logic. The optional Java gateway handles signed webhooks, queueing and retries.

Read the [architecture and approval flow](docs/architecture.md) for the boundaries between reviewing code, proposing an edit and publishing a fix.

### Design decisions

- **Async webhook handling.** A review takes 30–90 seconds with a real LLM, but GitHub times out
  webhooks after 10 seconds. The endpoint therefore only verifies and enqueues the job, then
  returns `202 Accepted`. A worker does the review.
- **The database is the queue.** Queued jobs survive restarts. Several gateway instances can poll safely
  because a JPA `@Version` optimistic lock decides which instance claims a job. Failed jobs retry
  with exponential backoff up to `max-attempts`, then are marked `FAILED` with the error.
- **Idempotent and supersedes stale work.** Duplicate deliveries (same `X-GitHub-Delivery`) are
  ignored. A new push to a PR marks older queued reviews of that PR `SUPERSEDED`, so no model
  calls are spent on outdated commits.
- **Bounded agent.** The loop is capped at `max_steps`. On the last step the model can submit its review. If it exhausts the budget without a valid submission, DevPilot reports an incomplete review.
- **Verifier guardrail.** The verifier applies hard rules after the model, and each dropped
  comment is recorded with its reason:
  - the file must be in the diff
  - the line must be added or modified (near misses within 2 lines are snapped onto the changed line)
  - confidence must meet the threshold
  - nits are filtered, along with duplicates and vague comments
  - at most 12 comments per review, ordered by severity
- **Human stays in charge.** Reviews are posted with `event: COMMENT`. DevPilot never approves
  or blocks a PR.
- **Provider-agnostic.** One internal message format, with adapters for Anthropic and for the
  OpenAI format. Gemini uses Google's OpenAI-compatible endpoint, and Gemini 3 *thought signatures*
  are carried through tool-call turns so multi-step reviews keep working. `OPENAI_BASE_URL` also
  works with Ollama or vLLM for self-hosted models.

---

## Quick start

Requirements: Python 3.10+ and git. For a model-backed review, supply an API key: a Gemini key from
[Google AI Studio](https://aistudio.google.com/apikey) (it starts with `AIza`), an Anthropic key or
an OpenAI key.

**One step:**

```bash
git clone https://github.com/yaswanth0702/devpilot-ai-code-reviewer.git
cd devpilot-ai-code-reviewer
bash scripts/setup_and_run.sh gemini     # or anthropic / openai
```

This creates `agent/.venv`, installs DevPilot, runs the tests, asks for your API key (hidden,
never saved) and runs the benchmark.

**Every new Terminal window** needs the environment activated and the key set:

```bash
cd devpilot-ai-code-reviewer && source agent/.venv/bin/activate
export GEMINI_API_KEY=AIza...            # or ANTHROPIC_API_KEY / OPENAI_API_KEY
```

Tip: `export DEVPILOT_PROVIDER=gemini` makes Gemini the default, so you can leave out `--provider`
(the pre-push hook relies on this too). With `--provider gemini`, DevPilot uses `gemini-3.1-flash-lite` with minimal reasoning by
default. That's fast, and it's the setup the published benchmark used. Override it with
`DEVPILOT_MODEL` and `DEVPILOT_REASONING_EFFORT`.

### Review your changes in a git repo

```bash

cd ~/code/my-project
devpilot review --provider gemini                    # uncommitted changes
devpilot review --provider gemini --staged           # staged changes only
devpilot review --provider gemini --base main        # your branch vs main
devpilot review --provider gemini --base HEAD~3      # the last 3 commits
devpilot review --provider gemini --format json      # machine-readable
devpilot review --provider gemini --fail-on critical # exit 1 on critical issues (for hooks/CI)
```

No API key yet? Add `--provider mock` to run the full pipeline with an offline, rule-based stand-in
(see [Results](#results)).

**Pre-push hook.** This blocks a push when DevPilot finds a critical issue:

```bash
scripts/install-pre-push-hook.sh ~/code/my-project
```

Example output: see [docs/local-mode-output.txt](docs/local-mode-output.txt).

---

## Paste code or check a single file

To try the browser workspace locally, install the Python service and start the offline provider:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ./agent
devpilot web --provider mock
```

Open the page printed in the terminal. Paste the snippet below or upload it as `Role.java`, then review it. Ask the chatbot why the comparison can fail. Preview the fix, approve it in the editor and download the result. Editing the source requires a fresh review.

```java
class Role {
    boolean isAdmin(String role) {
        return role == "admin";
    }
}
```

The offline demo can propose `"admin".equals(role)` for this example. For general review and open-ended discussion, select a configured model with `devpilot web --provider gemini`. Code sent for review or chat goes to that provider. See the [deployment guide](docs/deployment.md) to host the browser workspace.

**In the terminal:**
```bash
devpilot check src/app.py --provider gemini                 # review one file
devpilot check src/app.py --provider gemini --apply         # show diff, ask, then update this file
devpilot check src/app.py --provider gemini --fix           # show suggested changes as a diff
devpilot check src/app.py --provider gemini --fix --write   # + save to src/app.fixed.py
pbpaste | devpilot check --name app.py --provider gemini --fix   # review whatever you copied (macOS)
```

The fix step only applies the issues the review found and keeps everything else as it was. Read
the diff before using it, because AI-written fixes can be wrong.

**Real example:** pasting a small Java `Counter` class with three bugs (`==` on strings, an
unclosed `BufferedReader`, a non-atomic `count++`). DevPilot flagged all three and suggested this
fix:

```diff
+import java.util.concurrent.atomic.AtomicInteger;
-    private int count = 0;
+    private AtomicInteger count = new AtomicInteger(0);
-        count++;
+        count.incrementAndGet();
-        return role == "ADMIN";
+        return "ADMIN".equals(role);
-        BufferedReader reader = new BufferedReader(new FileReader(path));
-        return reader.readLine();
+        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
+            return reader.readLine();
+        }
```

The full review is in [docs/paste-review-example.md](docs/paste-review-example.md).

**Troubleshooting:**
- *"API key was rejected"* means the key isn't set or isn't valid. Run
  `export GEMINI_API_KEY=...` in the same Terminal window, then restart `devpilot web`.
- If port 8000 is busy because an old server is still running, stop it with
  `lsof -ti:8000 | xargs kill` or start on another port with `devpilot web --port 8001`.

---

## Use DevPilot with GitHub

Install the [review workflow](examples/devpilot-review.yml) in the target repository and configure its model provider. Eligible pull requests receive inline findings, and direct pushes receive a commit review. The workflow can also propose a patch for findings it can fix.

To apply a proposal, inspect its `preview.diff`, then use **Actions → DevPilot review → Run workflow** on the default branch. Select the approval operation and enter the review run ID and proposal digest from the review. DevPilot checks the approving user's permissions, the reviewed commit and the patch, then opens a fix PR. Merging that PR remains a separate decision.

For new repositories, configure the onboarding webhook once for the owner or organization you want covered. It can propose the workflow in a setup PR after the default branch exists. Empty repositories have no code to review. Installation instructions and event coverage are in the [architecture guide](docs/architecture.md).

[Example of an earlier inline review](https://github.com/yaswanth0702/devpilot-ai-code-reviewer/pull/1)

---

## Self-hosted server (Spring Boot gateway)

Use this if you want to run the review service yourself instead of in GitHub Actions.

### 1. Run the services

```bash
cp .env.example .env        # fill in ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET
docker compose up --build   # postgres + agent (:8000) + gateway (:8080)
```

`GITHUB_TOKEN` is a fine-grained personal access token with **Pull requests: Read and write** and
**Contents: Read** on the repos you want reviewed.

### 2. Expose the gateway and add a webhook

For local testing, expose the gateway with a tunnel, e.g. `ngrok http 8080`. Then in your repo, go
to **Settings → Webhooks → Add webhook** and set:

- **Payload URL:** `https://<your-tunnel>/webhooks/github`
- **Content type:** `application/json`
- **Secret:** the same value as `GITHUB_WEBHOOK_SECRET`
- **Events:** *Let me select individual events* → **Pull requests**

Open a PR, and within a minute or two DevPilot posts its review.
`GET http://localhost:8080/api/reviews` shows job status, attempts, timings and errors.

### Try GitHub mode without GitHub

`scripts/e2e_demo.sh` starts a fake GitHub API, the agent and the gateway, sends a **signed**
webhook, and prints the review that gets posted:

```bash
scripts/e2e_demo.sh            # offline (mock provider)
scripts/e2e_demo.sh anthropic  # real LLM, needs ANTHROPIC_API_KEY
```

Recorded output: [docs/e2e-demo-output.txt](docs/e2e-demo-output.txt).

---

## Results

### Agent contributions and verification

| Agent | Responsibility | Delivered and checked |
|---|---|---|
| 1. Architecture | Review and approval design, new repository setup | Documented the approval boundaries and implemented a signed GitHub webhook that offers a setup PR. Tests cover an empty repository, first push, duplicate deliveries and installation-token scope. |
| 2. Browser development | File upload, review chat and patch approval | Built the browser workspace, added contextual follow-up questions and a working offline example. Verified decline, approval and download in Chromium, including UTF-8 files with a byte order mark and Windows line endings. |
| 3. GitHub development | PR and push reviews, initial scans and approved fix PRs | Added patch artifacts, permission checks, revision checks and a separate fix PR. Tests exercise these operations with simulated GitHub responses. |
| 4. Deployment | Browser service and gateway configuration | Prepared the Railway service, runtime port and health check. Verified the browser flow locally with the offline provider. [Deployment guide](docs/deployment.md) |
| 5. Testing and debugging | Regression testing and end-to-end checks | Fixed exhausted review attempts reporting success. Checked failure handling, the Java gateway and the browser upload-to-download path using the offline provider. |

Run the Python and Java suites from the repository root:

```bash
(cd agent && python -m pytest -q)
(cd gateway && mvn test)
```

CI runs the agent tests on Python 3.10 and 3.12, plus the gateway tests and the offline benchmark, on
every push.

### End-to-end run

A signed webhook flows through gateway → queue → worker → agent → verifier → GitHub review API.
The job completed on the first attempt (`status: DONE`), and one inline comment was posted on the
right line of the PR. See [docs/e2e-demo-output.txt](docs/e2e-demo-output.txt).

### Seeded-bug benchmark

[`agent/evals/cases.py`](agent/evals/cases.py) contains 14 realistic PRs:

- 11 with a planted defect: SQL injection, `==` on strings, resource leak, race condition,
  `Optional.get()`, swallowed exception, off-by-one, hard-coded secret, mutable default argument,
  bare `except`, and an N+1 query
- 3 clean PRs that measure false positives

A comment counts as correct if it lands within ±2 lines of the planted bug.

```bash
cd agent
python -m evals.run_eval --provider mock        # offline baseline
python -m evals.run_eval --provider anthropic   # LLM agent (or openai / gemini)
```

Each run writes a Markdown and JSON report to `agent/evals/results/`.

| Reviewer | Precision | Recall | F1 | Bug-type accuracy | Clean PRs with false positives | Avg tool calls | Report |
|---|---|---|---|---|---|---|---|
| Rule-based baseline (`mock`, regex) | 1.000 | 0.273 | 0.429 | 1.000 | 0 / 3 | 3.0 | [mock.md](agent/evals/results/mock.md) |
| **LLM agent** (`gemini-3.1-flash-lite`, reasoning `minimal`) | **0.769** | **0.909** | **0.833** | 0.800 | 3 / 3 | 3.0 | [gemini.md](agent/evals/results/gemini.md) |

Gemini run: one pass over the 14 cases on 2026-11-22. The LLM agent found **10 of 11 planted
bugs** (recall 0.909), compared with 3 of 11 for the regex baseline. It caught the bugs that need
an understanding of the code: the race condition, the off-by-one error, the N+1 query and
`Optional.get()`. It missed the resource leak, where the reader isn't closed if an exception is
thrown. The weak spot is **false positives: it flagged one issue on each of the 3 clean PRs**, so
lowering noise on correct code is the next thing to improve, for example by tuning the verifier's
confidence threshold or adding a self-check step. Latency varied a lot (1–175 s per review)
because the API returned 503s and timeouts during the run, which DevPilot retried automatically.

When it found a bug, it named the right bug type (security, concurrency and so on) 80% of the time.
It used about 3 tool calls per review on average; on harder cases like `Optional.get()` and the
N+1 query it investigated further (7–8 tool calls). The whole run used about 46k tokens.

**Per case (Gemini):**

| Case | Found? | Tool calls |
|---|---|---|
| SQL injection (Java) | ✅ | 2 |
| `==` on strings (Java) | ✅ | 2 |
| Resource leak (Java) | ❌ missed | 1 |
| Race condition (Java) | ✅ | 2 |
| `Optional.get()` without check (Java) | ✅ | 7 |
| Swallowed exception (Java) | ✅ | 5 |
| Off-by-one (Java) | ✅ | 2 |
| Hard-coded secret (Python) | ✅ | 2 |
| Mutable default argument (Python) | ✅ | 1 |
| Bare `except` (Python) | ✅ | 2 |
| N+1 query (Python) | ✅ | 8 |
| Clean PR: Java refactor | ⚠️ 1 false positive | 2 |
| Clean PR: parameterized SQL (Python) | ⚠️ 1 false positive | 3 |
| Clean PR: try-with-resources (Java) | ⚠️ 1 false positive | 3 |

The summary report is [`agent/evals/results/gemini.md`](agent/evals/results/gemini.md); every
comment the agent made, with its line, severity and suggested fix, is in
[`gemini.json`](agent/evals/results/gemini.json).

These numbers come from a single run on a small benchmark, so treat them as indicative. To
reproduce them:

```bash
DEVPILOT_MODEL=gemini-3.1-flash-lite DEVPILOT_REASONING_EFFORT=minimal \
  python -m evals.run_eval --provider gemini
```

---

## Configuration

| Variable | Service | Default | Purpose |
|---|---|---|---|
| `DEVPILOT_PROVIDER` | agent | `anthropic` | `anthropic`, `openai`, `gemini` or `mock` |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | agent | none | provider API key |
| `DEVPILOT_MODEL` | agent | `gemini-3.1-flash-lite` / `claude-sonnet-5-5` / `gpt-4.1` | model override |
| `DEVPILOT_REASONING_EFFORT` | agent | `minimal` for Gemini | `minimal`, `low`, `medium` or `high` (OpenAI-format providers) |
| `DEVPILOT_TIMEOUT` | agent | `120` | seconds to wait per model call; requests are retried on timeouts, 429 and 5xx |
| `DEVPILOT_MAX_STEPS` | agent | `8` | tool-use step budget |
| `DEVPILOT_MIN_CONFIDENCE` | agent | `0.5` | verifier confidence threshold |
| `DEVPILOT_REVIEW_FILES` | Action | `code` | `code` reviews source/config files only; `all` reviews every file |
| `DEVPILOT_FAIL_ON_CRITICAL` | Action | `false` | fail the check on a critical issue |
| `OPENAI_BASE_URL` | agent | OpenAI | point at Ollama/vLLM for self-hosted models |
| `GITHUB_TOKEN` | both | none | read PRs, post reviews |
| `GITHUB_WEBHOOK_SECRET` | gateway | none | HMAC secret for webhook verification |
| `DATABASE_URL` | gateway | in-memory H2 | Postgres JDBC URL in production |
| `AGENT_URL` | gateway | `http://localhost:8000` | agent service address |

## Project structure

```
agent/                      Python agent service + CLI
  devpilot_agent/
    agent.py                bounded tool-use loop
    tools.py                read_file, search_code, submit_review schemas + executor
    verifier.py             guardrail rules
    diff_parser.py          unified diff -> changed-line map, code-file filter
    repo.py                 InMemory / LocalGit / GitHub PR / GitHub commit repos, BM25 code index
    llm.py                  Anthropic + OpenAI-format adapters (OpenAI, Gemini, Ollama), retries, test double
    mock_provider.py        offline rule-based stand-in
    app.py                  FastAPI: /review, /check, paste page at /, /health, /metrics
    cli.py                  `devpilot review`, `check` (single file / paste), `web`
    snippet.py              review pasted code and produce a fixed version + diff
    static/                 browser workspace, file selection, diff approval, review chat
    github_action.py        GitHub Action mode: PR reviews and direct-push commit comments
  evals/                    seeded-bug benchmark + runner + results
  tests/
gateway/                    Java 21 / Spring Boot 3.5 gateway
  webhook/                  HMAC verification, webhook controller
  review/                   job entity, repository, worker, read API
  client/                   agent + GitHub REST clients
action.yml                  GitHub Action definition
examples/                   workflow to copy into your repos
scripts/                    one-step setup, e2e demo, fake GitHub API, pre-push hook installer
docs/                       recorded outputs and the paste-review example
.github/workflows/
  ci.yml                    tests (Python 3.10 + 3.12, Java) + offline eval on every push
  devpilot-review.yml       DevPilot reviewing this repo's own PRs and pushes
docker-compose.yml
```

## Roadmap

- [x] GitHub Action: PR reviews, direct-push commit comments, code-only filtering
- [x] Paste code or check a single file, with a suggested fix shown as a diff
- [x] Gemini support (OpenAI-compatible endpoint, thought signatures), rate-limit-aware retries
- [ ] Cut false positives on clean PRs (currently 3/3 for Gemini Flash-Lite)
- [ ] One-click "Commit suggestion" buttons on PR comments (GitHub suggestion blocks)
- [ ] Run the benchmark against Claude, GPT and larger Gemini models and compare cost and latency per review
- [ ] Embedding-based code search alongside BM25 (hybrid retrieval)
- [ ] Re-review only new commits on `synchronize`, and resolve comments that were fixed
- [x] GitHub App installation tokens for new repository onboarding
- [ ] Installation tokens for the optional Java PR review gateway
- [ ] Run the project's tests in a sandbox as an agent tool
- [ ] Deploy to AWS (ECS Fargate + RDS) with Terraform

## License

MIT

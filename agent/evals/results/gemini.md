# DevPilot eval: `gemini` (gemini-3.1-flash-lite)

Run at 2026-11-22T16:26:54+00:00 on 14 cases x 1 repeat(s).

| Metric | Value |
|---|---|
| Precision | 0.769 |
| Recall | 0.909 |
| F1 | 0.833 |
| Category accuracy (of true positives) | 0.800 |
| Clean PRs with a false positive | 3 / 3 |
| Comments filtered by verifier | 0 |
| Median seconds per review | 54.445 |
| Avg tool calls per review | 3 |
| Total tokens | 46266 |

| Case | TP | FP | FN | Seconds | Tool calls |
|---|---|---|---|---|---|
| java-sql-injection | 1 | 0 | 0 | 4.75 | 2 |
| java-string-equality | 1 | 0 | 0 | 112.37 | 2 |
| java-resource-leak | 0 | 0 | 1 | 1.13 | 1 |
| java-race-condition | 1 | 0 | 0 | 124.93 | 2 |
| java-optional-get | 1 | 0 | 0 | 96.15 | 7 |
| java-swallowed-exception | 1 | 0 | 0 | 65.03 | 5 |
| java-off-by-one | 1 | 0 | 0 | 175.51 | 2 |
| py-hardcoded-secret | 1 | 0 | 0 | 1.54 | 2 |
| py-mutable-default | 1 | 0 | 0 | 46.63 | 1 |
| py-bare-except | 1 | 0 | 0 | 71.83 | 2 |
| py-n-plus-one | 1 | 0 | 0 | 29.1 | 8 |
| clean-java-refactor | 0 | 1 | 0 | 14.54 | 2 |
| clean-py-param-query | 0 | 1 | 0 | 7.78 | 3 |
| clean-java-try-with-resources | 0 | 1 | 0 | 62.26 | 3 |

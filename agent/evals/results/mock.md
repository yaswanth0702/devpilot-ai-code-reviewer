# DevPilot eval: `mock` (mock)

Run at 2026-11-22T01:20:09+00:00 on 14 cases x 1 repeat(s).

| Metric | Value |
|---|---|
| Precision | 1.000 |
| Recall | 0.273 |
| F1 | 0.429 |
| Category accuracy (of true positives) | 1.000 |
| Clean PRs with a false positive | 0 / 3 |
| Comments filtered by verifier | 0 |
| Median seconds per review | 0.0 |
| Avg tool calls per review | 3 |
| Total tokens | 0 |

| Case | TP | FP | FN | Seconds | Tool calls |
|---|---|---|---|---|---|
| java-sql-injection | 0 | 0 | 1 | 0.0 | 3 |
| java-string-equality | 0 | 0 | 1 | 0.0 | 3 |
| java-resource-leak | 0 | 0 | 1 | 0.0 | 3 |
| java-race-condition | 0 | 0 | 1 | 0.0 | 3 |
| java-optional-get | 0 | 0 | 1 | 0.0 | 3 |
| java-swallowed-exception | 1 | 0 | 0 | 0.0 | 3 |
| java-off-by-one | 0 | 0 | 1 | 0.0 | 3 |
| py-hardcoded-secret | 1 | 0 | 0 | 0.0 | 3 |
| py-mutable-default | 0 | 0 | 1 | 0.0 | 3 |
| py-bare-except | 1 | 0 | 0 | 0.0 | 3 |
| py-n-plus-one | 0 | 0 | 1 | 0.0 | 3 |
| clean-java-refactor | 0 | 0 | 0 | 0.0 | 3 |
| clean-py-param-query | 0 | 0 | 0 | 0.0 | 3 |
| clean-java-try-with-resources | 0 | 0 | 0 | 0.0 | 3 |

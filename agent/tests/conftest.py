import pytest

SAMPLE_DIFF = """diff --git a/src/UserService.java b/src/UserService.java
index 111..222 100644
--- a/src/UserService.java
+++ b/src/UserService.java
@@ -10,6 +10,9 @@ public class UserService {
     public User find(String name) {
-        return repo.byName(name);
+        if (name == "admin") {
+            return null;
+        }
+        return repo.byName(name);
     }

     public void save(User u) {
"""

SAMPLE_FILES = {
    "src/UserService.java": "\n".join(
        ["// header"] * 9
        + [
            "public class UserService {",
            "    public User find(String name) {",
            '        if (name == "admin") {',
            "            return null;",
            "        }",
            "        return repo.byName(name);",
            "    }",
            "",
            "    public void save(User u) {",
            "        repo.save(u);",
            "    }",
            "}",
        ]
    ),
    "src/UserRepository.java": "public interface UserRepository { User byName(String name); void save(User u); }",
}


@pytest.fixture
def sample_diff():
    return SAMPLE_DIFF


@pytest.fixture
def sample_files():
    return dict(SAMPLE_FILES)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Tests must not depend on the developer's DEVPILOT_* settings or on the GitHub Actions
    environment they may be running in (GITHUB_EVENT_NAME, GITHUB_STEP_SUMMARY, ...)."""
    import os

    for name in list(os.environ):
        if name.startswith(("DEVPILOT_", "GITHUB_")) or name in ("OPENAI_BASE_URL",):
            monkeypatch.delenv(name, raising=False)

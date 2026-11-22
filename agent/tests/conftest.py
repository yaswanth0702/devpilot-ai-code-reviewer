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

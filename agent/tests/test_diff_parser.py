from devpilot_agent.diff_parser import filter_code_diff, is_code_file, parse_unified_diff


def test_added_and_context_lines(sample_diff):
    files = parse_unified_diff(sample_diff)
    fd = files["src/UserService.java"]
    assert fd.added_lines == {11, 12, 13, 14}
    assert {10, 15, 16, 17} <= fd.context_lines
    assert 11 in fd.commentable_lines


def test_multiple_files_and_new_file():
    diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,3 @@
 x = 1
+y = 2
 z = 3
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+print("hi")
+print("bye")
"""
    files = parse_unified_diff(diff)
    assert files["a.py"].added_lines == {2}
    assert files["new.py"].added_lines == {1, 2}


def test_deleted_file_is_ignored():
    diff = """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-a = 1
-b = 2
"""
    assert parse_unified_diff(diff) == {}


def test_multiple_hunks():
    diff = """--- a/f.txt
+++ b/f.txt
@@ -1,2 +1,2 @@
-a
+A
 b
@@ -50,2 +50,3 @@
 x
+y
 z
"""
    assert parse_unified_diff(diff)["f.txt"].added_lines == {1, 51}


def test_is_code_file():
    for p in ["a.py", "src/App.java", "web/x.tsx", "infra/main.tf", "Dockerfile", "Dockerfile.dev", "pom.xml", "ci.yml"]:
        assert is_code_file(p), p
    for p in ["README.md", "docs/guide.txt", "logo.png", "package-lock.json", "data.csv", "LICENSE", ".gitignore"]:
        assert not is_code_file(p), p


def test_filter_code_diff_keeps_only_code_sections():
    diff = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 x
+y
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
 a = 1
+b = 2
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone = True
"""
    kept, skipped = filter_code_diff(diff)
    assert "app.py" in kept and "old.py" in kept and "README.md" not in kept
    assert skipped == ["README.md"]
    assert set(parse_unified_diff(kept)) == {"app.py"}

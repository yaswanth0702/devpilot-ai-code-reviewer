# Paste review example (real run)

Run on 2026-11-22 with `devpilot web --provider gemini` (`gemini-3.1-flash-lite`, reasoning
`minimal`), "Suggest fixed code" checked. This is the output from that run.

## Input (`Counter.java`)

```java
import java.io.*;

public class Counter {
    private int count = 0;

    public void increment() {
        count++;
    }

    public boolean isAdmin(String role) {
        return role == "ADMIN";
    }

    public String firstLine(String path) throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader(path));
        return reader.readLine();
    }
}
```

## Review

**Summary:** The `Counter` class has three major issues: a bug in string comparison, a resource
leak in file I/O, and a concurrency issue in the shared state. These should be addressed before
the code is used in production.

*3 issue(s) · 0 filtered by verifier · 1 tool call*

| Line | Severity · category | Issue | Suggested fix |
|---|---|---|---|
| 11 | major · bug | `==` compares references, not contents; `role == "ADMIN"` is often false even for "ADMIN" | `return "ADMIN".equals(role);` |
| 15 | major · bug | `BufferedReader` is never closed, so frequent calls leak file descriptors | try-with-resources |
| 4 | major · concurrency | `count++` is not atomic; concurrent `increment()` calls lose updates | `AtomicInteger` or `synchronized` |

## Suggested changes

> Changed `count` to `AtomicInteger` and updated `increment()` to use `incrementAndGet()` for
> thread safety. Updated `isAdmin()` to use `.equals()`. Used try-with-resources in `firstLine()`
> to ensure the `BufferedReader` is closed.

```diff
--- Counter.java (original)
+++ Counter.java (fixed)
@@ -1,18 +1,20 @@
 import java.io.*;
+import java.util.concurrent.atomic.AtomicInteger;
 
 public class Counter {
-    private int count = 0;
+    private AtomicInteger count = new AtomicInteger(0);
 
     public void increment() {
-        count++;
+        count.incrementAndGet();
     }
 
     public boolean isAdmin(String role) {
-        return role == "ADMIN";
+        return "ADMIN".equals(role);
     }
 
     public String firstLine(String path) throws IOException {
-        BufferedReader reader = new BufferedReader(new FileReader(path));
-        return reader.readLine();
+        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
+            return reader.readLine();
+        }
     }
 }
```

All three planted bugs were found, and the fix changed only the affected lines. It also added the
missing import, and `"ADMIN".equals(role)` is null-safe.

#!/usr/bin/env bash
# Installs a git pre-push hook that runs DevPilot on your branch and blocks the push
# if it finds a critical issue. Usage: scripts/install-pre-push-hook.sh /path/to/your/repo
set -euo pipefail
target="${1:-.}"
hook="$(git -C "$target" rev-parse --git-path hooks)/pre-push"
cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
base="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)"
echo "DevPilot: reviewing changes against $base ..."
devpilot review --base "$base" --fail-on critical || {
  echo "DevPilot found a critical issue. Fix it, or push with --no-verify to skip."
  exit 1
}
HOOK
chmod +x "$hook"
echo "Installed pre-push hook at $hook"

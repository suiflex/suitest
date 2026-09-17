#!/usr/bin/env python3
"""
Pre-Commit Guard for Suitest:
1. Prevents staging/committing local secrets (.env, .env.local, credentials, etc.)
2. Prevents unauthorized relaxation of .forgeguard/config.toml
"""

import subprocess
import sys


def run_cmd(cmd: str) -> tuple[int, str]:
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.returncode, (res.stdout + "\n" + res.stderr).strip()


def main():
    # 1. Inspect staged files
    code, out = run_cmd("git diff --cached --name-only")
    if code != 0 or not out:
        sys.exit(0)

    staged_files = [f.strip() for f in out.splitlines() if f.strip()]
    if not staged_files:
        sys.exit(0)

    errors: list[str] = []

    # Check for leaked sensitive/personal files
    for f in staged_files:
        if (
            f == ".env"
            or f.startswith(".env.")
            or f.endswith(".local")
            or "credentials.json" in f
            or ".suitest-dev" in f
            or f.endswith(".pem")
            or f.endswith(".key")
        ) and not f.endswith(".example"):
            errors.append(
                f"❌ [ANTI-LEAK] Attempted to commit private/local file: '{f}'\n"
                f"   -> Remedy: Unstage with 'git restore --staged {f}' and keep it in .gitignore."
            )

    # Check for policy relaxation in .forgeguard/config.toml
    if ".forgeguard/config.toml" in staged_files:
        _, diff_out = run_cmd("git diff --cached -- .forgeguard/config.toml")
        tampered = False
        reasons = []
        for line in diff_out.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added = line[1:].strip()
                if "block = false" in added or "block=false" in added:
                    tampered = True
                    reasons.append(f"Adding relaxation: '{added}'")
                if (
                    'mode = "lite"' in added
                    or 'mode = "default"' in added
                    or 'mode="lite"' in added
                    or 'mode="default"' in added
                ):
                    tampered = True
                    reasons.append(f"Lowering strictness mode: '{added}'")
        if tampered:
            errors.append(
                "❌ [ANTI-LEAK] Unauthorized relaxation detected in staged '.forgeguard/config.toml':\n"
                + "\n".join(f"   • {r}" for r in reasons)
                + "\n   -> Remedy: Discard staged changes with 'git restore --staged .forgeguard/config.toml'."
            )

    if errors:
        print("\n==================================================")
        print("🛑  [pre-commit hook] Commit Aborted by Policy Guard")
        print("==================================================")
        for e in errors:
            print(e)
        print("==================================================\n")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()

"""Security & Vulnerability Audit Gate (Software Engineering Master Checklist S11 & S12).

Orchestrates pip-audit with documented vulnerability exceptions, compensating
controls, and expiration dates.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

# Documented exceptions with expiration dates and compensating controls (Master Checklist S12)
VULNERABILITY_EXCEPTIONS: dict[str, dict[str, str]] = {
    "pillow": {
        "reason": (
            "Transitive dependency pulled in by Streamlit (<1.60) to maintain "
            "Python 3.10 runtime support. Upstream Streamlit pins pillow<13."
        ),
        "compensating_control": (
            "SchemaSense is a database schema assistant and SQL query generator. "
            "It contains zero image processing, file upload image parsing, or "
            "Pillow API invocations. Pillow code paths are completely unreachable "
            "from user input."
        ),
        "expires": "2027-01-01",
    }
}


def run_audit(requirements_file: str = "requirements.txt") -> int:
    print(f"[*] Running pip-audit on {requirements_file}...")
    cmd = [sys.executable, "-m", "pip_audit", "-r", requirements_file, "-f", "json"]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    stdout = proc.stdout.strip()
    if not stdout:
        if proc.returncode != 0:
            print(f"[!] pip-audit failed to execute:\n{proc.stderr}", file=sys.stderr)
            return proc.returncode
        print("[+] pip-audit returned no vulnerabilities.")
        return 0

    try:
        report = json.loads(stdout)
    except json.JSONDecodeError:
        print("[!] Failed to parse pip-audit JSON output:", file=sys.stderr)
        print(stdout, file=sys.stderr)
        return 1

    dependencies = report.get("dependencies", [])
    violations: list[dict] = []
    accepted_exceptions: list[dict] = []
    now = datetime.now(timezone.utc)

    for dep in dependencies:
        vulns = dep.get("vulns", [])
        if not vulns:
            continue

        name = dep.get("name", "").lower()
        version = dep.get("version", "")

        if name in VULNERABILITY_EXCEPTIONS:
            exc = VULNERABILITY_EXCEPTIONS[name]
            expires_dt = datetime.fromisoformat(exc["expires"]).replace(
                tzinfo=timezone.utc
            )
            if now <= expires_dt:
                accepted_exceptions.append(
                    {
                        "package": name,
                        "version": version,
                        "vuln_count": len(vulns),
                        "exception": exc,
                    }
                )
                continue
            else:
                print(
                    f"[!] Exception for '{name}' expired on {exc['expires']}",
                    file=sys.stderr,
                )

        violations.append(
            {
                "package": name,
                "version": version,
                "vulns": vulns,
            }
        )

    if accepted_exceptions:
        print("\n=== DOCUMENTED VULNERABILITY EXCEPTIONS (S12) ===")
        for item in accepted_exceptions:
            print(
                f"[ACCEPTED EXCEPTION] {item['package']}=={item['version']} ({item['vuln_count']} advisories)"
            )
            print(f"  Reason:               {item['exception']['reason']}")
            print(
                f"  Compensating Control: {item['exception']['compensating_control']}"
            )
            print(f"  Valid Until:          {item['exception']['expires']}")
        print("================================================\n")

    if violations:
        print(
            f"\n[FAIL] Found {len(violations)} unapproved vulnerable package(s):",
            file=sys.stderr,
        )
        for v in violations:
            print(
                f"  - {v['package']}=={v['version']}: {len(v['vulns'])} vulnerability advisories",
                file=sys.stderr,
            )
            for adv in v["vulns"]:
                print(
                    f"      * {adv.get('id')}: {adv.get('description', '')[:100]}...",
                    file=sys.stderr,
                )
        return 1

    print("[PASS] Security vulnerability audit passed. Zero unhandled vulnerabilities.")
    return 0


if __name__ == "__main__":
    sys.exit(run_audit())

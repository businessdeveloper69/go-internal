"""Run go-internal's full tests and check that the PR-specific regression ran."""
import json
import os
import subprocess
import sys
from pathlib import Path

REVISIONS = {
    "318": ("cf5f008674e1934225fc19f2a2774542fb2fdff6", "imports",
            {"TestScanAndroid", "TestMatchFileAndroid"}),
    "319": ("7c5c000d7b8f992c35b8e35900a242153e861a0d", "testscript",
            {"TestScripts/either_status"}),
}


def inspect_events(events, packages, target_package, required):
    ended = {e["Package"] for e in events if not e.get("Test") and e["Action"] in ("pass", "skip")}
    passed = {(e["Package"], e["Test"]) for e in events if e.get("Test") and e["Action"] == "pass"}
    skipped = [(e["Package"], e["Test"]) for e in events if e.get("Test") and e["Action"] == "skip"]
    failed = [e for e in events if e["Action"] in ("fail", "build-fail")]
    targets = {t for pkg, t in passed if pkg == target_package}
    return {"packages_accounted": ended == set(packages), "packages": len(ended),
            "tests_and_subtests_passed": len(passed), "skips": skipped,
            "regressions_passed": sorted(required & targets), "failures": failed}


def main():
    pr, os_name, version_family = sys.argv[1:]
    sha, target, required = REVISIONS[pr]
    dest = Path("pr" + pr)
    def output(*args):
        return subprocess.check_output(args, cwd=dest, text=True).strip()
    assert output("git", "rev-parse", "HEAD") == sha
    env = json.loads(output("go", "env", "-json", "GOOS", "GOARCH", "GOVERSION", "CGO_ENABLED"))
    assert env["GOOS"] == os_name and env["GOVERSION"].startswith("go" + version_family + ".") and env["CGO_ENABLED"] == "1", env
    packages = output("go", "list", "./...").splitlines()
    module = output("go", "list", "-m")
    rows = {}
    for mode, flags in (("normal", []), ("race", ["-race"])):
        cmd = ["go", "test", "-json", "-count=1", *flags, "./..."]
        print("Running", cmd, env, flush=True)
        proc = subprocess.run(cmd, cwd=dest, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        row = inspect_events(events, packages, module + "/" + target, required)
        row["exit"] = proc.returncode
        row["success"] = (proc.returncode == 0 and not row["failures"] and row["packages_accounted"] and set(row["regressions_passed"]) == required)
        rows[mode] = row
        if not row["success"]:
            failed_pkgs = {e.get("FailedBuild", e.get("Package")) for e in row["failures"]}
            for ev in events:
                if ev.get("Package") in failed_pkgs and ev.get("Output"):
                    print(ev["Output"].rstrip(), flush=True)
            print(proc.stderr.decode(errors="replace")[-3000:])
        print(mode, json.dumps(row), flush=True)
    record = {"pr": pr, "sha": sha, "environment": env, "suites": rows}
    dest = Path("receipts")
    dest.mkdir(exist_ok=True)
    (dest / (pr + ".json")).write_text(json.dumps(record, indent=2) + "\n")
    if not all(row["success"] for row in rows.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Check `e2e run` against demo_app: exit code 1 with exactly 23 passed / 3 intentional failures.

Usage: check_e2e_report.py REPORT_JSON EXIT_CODE
Prints a Markdown summary to stdout (CI appends it to the job summary); exits 1 on mismatch.
"""
import json
import sys

EXPECTED = {"passed": 23, "failed": 3, "errored": 0, "total": 26}
EXPECTED_EXIT_CODE = 1  # the 3 failing demo tests are intentional


def main() -> int:
    report_path, exit_code = sys.argv[1], int(sys.argv[2])
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    actual = {key: report[key] for key in EXPECTED}
    print("### e2e run on demo_app")
    print(
        f"**{actual['passed']} passed**, {actual['failed']} failed (intentional), "
        f"{actual['errored']} errors, {report['duration']:.1f}s, exit code {exit_code}"
    )

    problems = []
    if exit_code != EXPECTED_EXIT_CODE:
        problems.append(f"exit code {exit_code}, expected {EXPECTED_EXIT_CODE}")
    if actual != EXPECTED:
        problems.append(f"results {actual}, expected {EXPECTED}")
    for problem in problems:
        print(f"- ❌ {problem}")
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

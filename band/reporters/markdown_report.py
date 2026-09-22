import datetime
from pathlib import Path
from typing import Any, Dict, List

def write_markdown_report(
    task_dir: Path,
    slug: str,
    passed: bool,
    results: List[Dict[str, Any]],
    duration_total_ms: float
) -> None:
    artifacts_dir = task_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_file = artifacts_dir / "done-report.md"

    status_badge = "🟢 PASSED" if passed else "🔴 FAILED"
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    lines = [
        f"# Done Verification Report: `{slug}`",
        f"**Status:** {status_badge}  ",
        f"**Timestamp:** `{timestamp}`  ",
        f"**Total Duration:** `{duration_total_ms:.1f}ms`  ",
        "",
        "## Claim Results",
        "",
        "| Status | Claim ID | Kind | Duration | Message |",
        "| :---: | :--- | :--- | :---: | :--- |",
    ]

    for r in results:
        badge = "✅" if r["passed"] else "❌"
        msg = r.get("message", "").replace("\n", "<br/>") or "Passed"
        lines.append(f"| {badge} | `{r['claim_id']}` | `{r['kind']}` | {r['duration_ms']:.0f}ms | {msg} |")

    report_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

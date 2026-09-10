"""Source-level checks for the macOS workflow distribution contract."""

from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[2] / ".github/workflows/build-and-release.yml").read_text(encoding="utf-8")


def workflow_section(start, end):
    return WORKFLOW.split(f"\n  {start}:\n", 1)[1].split(f"\n  {end}:\n", 1)[0]


def test_all_macos_workflow_builds_are_sent_for_signing():
    gui_job = workflow_section("gui-release", "macos-release")
    assert "python build_macos.py --app-only" in gui_job
    assert "if: matrix.label == 'macos'\n        uses: actions/upload-artifact@v4" in gui_job
    assert "python build_macos.py\n" not in gui_job


def test_signing_job_runs_for_tags_and_manual_builds():
    signing_job = WORKFLOW.split("\n  macos-release:\n", 1)[1]
    header = signing_job.split("\n    steps:\n", 1)[0]
    assert "startsWith(github.ref, 'refs/tags/')" not in header
    assert "Upload signed macOS workflow artifacts" in signing_job
    assert "Upload signed macOS release assets" in signing_job

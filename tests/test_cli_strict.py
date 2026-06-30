"""CLI `--strict` flag: an output-stage drop becomes a non-zero exit.

`on_missing:"error"` (and any required miss) drops a profile and records a
`projection` skip while the batch continues (exit 0). `--strict` turns that
into exit 2, without making graceful adapter skips a failure.
"""

import json

from candidate_pipeline.cli import main


def _error_config(tmp_path):
    """A config whose required field most fixtures lack -> projection skips."""
    cfg = {
        "on_missing": "error",
        "fields": [
            {"path": "yrs", "from": "years_experience", "type": "number", "required": True},
        ],
    }
    path = tmp_path / "err_config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def _argv(csv_path, ats_path, github_path, *extra):
    return [
        "transform",
        "--inputs",
        f"csv={csv_path}",
        f"ats={ats_path}",
        f"github={github_path}",
        "--default-region",
        "IN",
        "--as-of",
        "2026-06-30",
        *extra,
    ]


def test_error_config_without_strict_exits_zero(tmp_path, csv_path, ats_path, github_path, capsys):
    cfg = _error_config(tmp_path)
    rc = main(_argv(csv_path, ats_path, github_path, "--config", cfg))
    assert rc == 0  # profiles dropped, but the batch still succeeds


def test_error_config_with_strict_exits_nonzero(tmp_path, csv_path, ats_path, github_path, capsys):
    cfg = _error_config(tmp_path)
    rc = main(_argv(csv_path, ats_path, github_path, "--config", cfg, "--strict"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "strict: dropped" in err
    assert "projection" in err


def test_strict_on_clean_default_run_exits_zero(csv_path, ats_path, github_path):
    # Default config emits every fixture profile -> no output-stage skips.
    rc = main(_argv(csv_path, ats_path, github_path, "--strict"))
    assert rc == 0


def test_strict_does_not_fail_on_adapter_skip(tmp_path, csv_path, ats_path, capsys):
    # A garbage/missing source is a graceful adapter skip, NOT a strict failure.
    missing = str(tmp_path / "nope.json")
    rc = main(
        [
            "transform",
            "--inputs",
            f"csv={csv_path}",
            f"ats={ats_path}",
            f"github={missing}",
            "--default-region",
            "IN",
            "--as-of",
            "2026-06-30",
            "--strict",
        ]
    )
    assert rc == 0

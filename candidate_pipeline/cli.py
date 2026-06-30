"""CLI entry point (PRD §12): `transform` and `validate-config`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from candidate_pipeline.config.loader import DEFAULT_CONFIG, load_config
from candidate_pipeline.pipeline import run_pipeline


def _parse_inputs(pairs: list[str]) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--inputs expects key=path, got '{pair}'")
        key, path = pair.split("=", 1)
        inputs[key] = path
    return inputs


def _parse_as_of(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _cmd_transform(args: argparse.Namespace) -> int:
    inputs = _parse_inputs(args.inputs)
    config = load_config(args.config) if args.config else DEFAULT_CONFIG

    outputs, _profiles, report = run_pipeline(
        inputs,
        config,
        default_region=args.default_region,
        as_of=_parse_as_of(args.as_of),
        live=args.live,
    )

    out_text = json.dumps(outputs, indent=2 if args.pretty else None, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out_text)
    if args.pretty or not args.out:
        print(out_text)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report.model_dump(), fh, indent=2, ensure_ascii=False)

    print(
        f"profiles_out={report.counts.get('profiles_out', 0)} "
        f"records_in={report.counts.get('records_in', 0)} "
        f"sources_skipped={report.counts.get('sources_skipped', 0)}",
        file=sys.stderr,
    )
    return 0


def _cmd_validate_config(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {len(cfg.fields)} fields, on_missing={cfg.on_missing}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candidate-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("transform", help="run the pipeline end-to-end")
    t.add_argument("--inputs", nargs="+", required=True, metavar="key=path",
                   help="e.g. csv=recruiter.csv ats=ats.json github=github.json")
    t.add_argument("--config", default=None, help="projection config JSON (default: built-in)")
    t.add_argument("--default-region", default=None, help="ISO region for phones without a country code")
    t.add_argument("--out", default=None, help="write output JSON here")
    t.add_argument("--report", default=None, help="write the RunReport JSON here")
    t.add_argument("--live", action="store_true", help="no-op GitHub stub (defaults to fixture)")
    t.add_argument("--pretty", action="store_true", help="pretty-print and echo to stdout")
    t.add_argument("--as-of", default=None, help="YYYY-MM-DD pin for recency/years_experience")
    t.set_defaults(func=_cmd_transform)

    v = sub.add_parser("validate-config", help="validate a projection config")
    v.add_argument("--config", required=True)
    v.set_defaults(func=_cmd_validate_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

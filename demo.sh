#!/usr/bin/env bash
# Demo helper for the ~2-minute walkthrough. Wraps the two pipeline runs so the
# on-camera step is a single short command.
#
#   ./demo.sh            # default schema  -> sample_output/profiles.json + report.json
#   ./demo.sh custom     # custom config   -> sample_output/profiles_custom.json
#
# The pretty JSON is written to sample_output/ (open it in the editor); stdout is
# suppressed so the terminal stays clean. The pipeline's own summary line
# (profiles_out=.. records_in=.. sources_skipped=..) still prints via stderr.
set -euo pipefail

INPUTS=(
  csv=candidate_pipeline/data/fixtures/recruiter.csv
  ats=candidate_pipeline/data/fixtures/ats.json
  github=candidate_pipeline/data/fixtures/github.json
  resume=candidate_pipeline/data/fixtures/resume.pdf
)

mode="${1:-default}"

case "$mode" in
  default)
    echo "== default schema =="
    candidate-pipeline transform \
      --inputs "${INPUTS[@]}" \
      --default-region IN --as-of 2026-06-30 \
      --out sample_output/profiles.json \
      --report sample_output/report.json \
      --pretty >/dev/null
    ;;
  custom)
    echo "== custom config =="
    candidate-pipeline transform \
      --inputs "${INPUTS[@]}" \
      --config candidate_pipeline/data/configs/custom_config.json \
      --default-region IN --as-of 2026-06-30 \
      --out sample_output/profiles_custom.json \
      --pretty >/dev/null
    ;;
  *)
    echo "usage: ./demo.sh [default|custom]" >&2
    exit 1
    ;;
esac

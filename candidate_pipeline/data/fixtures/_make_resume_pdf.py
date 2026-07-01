"""Generate `resume.pdf` from `resume.txt` (single-column, text-extractable).

Dev-only helper — reportlab is a `dev` optional dependency, not a runtime one.
Regenerate after editing resume.txt:

    python candidate_pipeline/data/fixtures/_make_resume_pdf.py

The résumé adapter reads the PDF via pypdf at runtime; this script only builds
the fixture. A broken/garbage PDF for the resilience test is written too.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

_HERE = Path(__file__).parent


def make_pdf(txt_path: Path, pdf_path: Path) -> None:
    lines = txt_path.read_text(encoding="utf-8").splitlines()
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.setFont("Helvetica", 11)
    _, height = letter
    y = height - 72
    for line in lines:
        c.drawString(72, y, line)
        y -= 16
    c.save()


def main() -> None:
    make_pdf(_HERE / "resume.txt", _HERE / "resume.pdf")
    # a deliberately corrupt PDF for the skip-not-crash resilience test
    (_HERE / "edge" / "resume_broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf \x00\x01\x02")
    print("wrote resume.pdf and edge/resume_broken.pdf")


if __name__ == "__main__":
    main()

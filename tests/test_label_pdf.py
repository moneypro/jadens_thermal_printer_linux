"""
Tests for LabelPDF — the PDF preparation / cropping module.
Goal: any input PDF produces a valid, portrait 4x6 vector PDF.
"""

import subprocess
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from print_label import LabelPDF, LABEL_W_PTS, LABEL_H_PTS, MAX_MARGIN_PTS, ExcessiveMarginError

FIXTURES = Path(__file__).parent / "fixtures"
LETTER_LABEL = FIXTURES / "shipping_label_letter.pdf"   # 8.5x11 with label in top half
SIZED_LABEL  = FIXTURES / "Labels-Sample.pdf"           # already ~4x6

TOLERANCE_PTS = 36  # ±0.5 inch — "satisfied the minimum"


def pdf_size_pts(path: str) -> tuple[float, float]:
    """Return effective display (width, height) in points, accounting for /Rotate."""
    out = subprocess.run(["pdfinfo", path], capture_output=True, text=True).stdout
    w, h, rot = 0.0, 0.0, 0
    for line in out.splitlines():
        if line.startswith("Page size:"):
            parts = line.split()
            w, h = float(parts[2]), float(parts[4])
        if line.startswith("Page rot:"):
            rot = int(line.split()[2])
    if rot in (90, 270):
        w, h = h, w
    if w == 0:
        raise ValueError(f"Could not read size from {path}")
    return w, h


def is_portrait_4x6(w: float, h: float) -> bool:
    return (
        abs(w - LABEL_W_PTS) <= TOLERANCE_PTS and
        abs(h - LABEL_H_PTS) <= TOLERANCE_PTS
    )


# ── Already-sized PDF (Labels-Sample.pdf ~3.81" x 6") ────────────────────────

class TestAlreadySized:
    def test_returns_original_path(self):
        """No crop needed → original path is returned, no temp file created."""
        with LabelPDF(str(SIZED_LABEL)) as label:
            result = label.prepare()
        assert result == str(SIZED_LABEL)

    def test_no_temp_file_created(self):
        """Context exit should leave no temp files."""
        with LabelPDF(str(SIZED_LABEL)) as label:
            result = label.prepare()
            tmp = label._cropped_tmp
        assert tmp is None

    def test_output_dimensions_within_tolerance(self):
        """Output dimensions should be within ±0.5 inch of 4x6."""
        with LabelPDF(str(SIZED_LABEL)) as label:
            result = label.prepare()
        w, h = pdf_size_pts(result)
        assert is_portrait_4x6(w, h), f"Expected ~{LABEL_W_PTS}x{LABEL_H_PTS} pts, got {w:.1f}x{h:.1f}"


# ── Letter-size PDF (shipping_label_letter.pdf 8.5x11) ───────────────────────

class TestLetterSizeCrop:
    def test_returns_different_path(self):
        """Crop needed → a new temp file is returned."""
        with LabelPDF(str(LETTER_LABEL)) as label:
            result = label.prepare()
        assert result != str(LETTER_LABEL)

    def test_output_is_valid_pdf(self):
        """Cropped output must be a valid PDF file."""
        with LabelPDF(str(LETTER_LABEL)) as label:
            result = label.prepare()
            with open(result, "rb") as f:
                header = f.read(4)
        assert header == b"%PDF", f"Output does not start with %PDF"

    def test_output_dimensions_portrait_4x6(self):
        """Cropped output must be portrait 4x6 within ±0.5 inch."""
        with LabelPDF(str(LETTER_LABEL)) as label:
            result = label.prepare()
            w, h = pdf_size_pts(result)
        assert is_portrait_4x6(w, h), f"Expected ~{LABEL_W_PTS}x{LABEL_H_PTS} pts, got {w:.1f}x{h:.1f}"

    def test_temp_file_cleaned_up_after_close(self):
        """Temp file must be deleted after close()."""
        label = LabelPDF(str(LETTER_LABEL))
        result = label.prepare()
        assert Path(result).exists()
        label.close()
        assert not Path(result).exists()

    def test_temp_file_cleaned_up_after_context_exit(self):
        """Temp file must be deleted after __exit__."""
        with LabelPDF(str(LETTER_LABEL)) as label:
            result = label.prepare()
        assert not Path(result).exists()

    def test_double_close_is_safe(self):
        """Calling close() twice should not raise."""
        label = LabelPDF(str(LETTER_LABEL))
        label.prepare()
        label.close()
        label.close()  # should not raise


# ── Margin validation ─────────────────────────────────────────────────────────

class TestValidation:
    def test_already_sized_margins_within_limit(self):
        """Already-sized PDF should have margins within MAX_MARGIN_PTS."""
        with LabelPDF(str(SIZED_LABEL)) as label:
            result = label.prepare()
            margins = label.validate(result)
        for side, pts in margins.items():
            assert pts <= MAX_MARGIN_PTS, \
                f"{side} margin {pts:.1f}pts exceeds limit {MAX_MARGIN_PTS}pts"

    def test_letter_size_margins_within_limit(self):
        """Cropped letter-size PDF should have margins within MAX_MARGIN_PTS."""
        with LabelPDF(str(LETTER_LABEL)) as label:
            result = label.prepare()
            margins = label.validate(result)
        for side, pts in margins.items():
            assert pts <= MAX_MARGIN_PTS, \
                f"{side} margin {pts:.1f}pts exceeds limit {MAX_MARGIN_PTS}pts"

    def test_validate_returns_all_four_sides(self):
        """validate() must return margins for all four sides."""
        with LabelPDF(str(LETTER_LABEL)) as label:
            result = label.prepare()
            margins = label.validate(result)
        assert set(margins.keys()) == {"left", "right", "top", "bottom"}

    def test_prepare_raises_on_excessive_margin(self, tmp_path):
        """A PDF with only tiny content (huge margins) must raise ExcessiveMarginError."""
        # Build a minimal PDF with a tiny dot near the centre — lots of whitespace
        tiny_pdf = tmp_path / "tiny.pdf"
        subprocess.run([
            "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
            "-dDEVICEWIDTHPOINTS=288", "-dDEVICEHEIGHTPOINTS=432",
            f"-sOutputFile={tiny_pdf}",
            "-c", "0 0 moveto 288 432 lineto stroke showpage",
        ], check=True, capture_output=True)
        # tiny_pdf is already 4x6 so prepare() won't crop, but validate() should
        # see zero margin (content fills the page), so it passes.
        # Instead test validate() directly on a blank-ish PDF:
        blank_pdf = tmp_path / "blank.pdf"
        subprocess.run([
            "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
            "-dDEVICEWIDTHPOINTS=288", "-dDEVICEHEIGHTPOINTS=432",
            f"-sOutputFile={blank_pdf}",
            "-c", "144 216 moveto (X) show showpage",   # single char at centre
        ], check=True, capture_output=True)
        with LabelPDF(str(blank_pdf)) as label:
            with pytest.raises(ExcessiveMarginError):
                label.validate(str(blank_pdf))

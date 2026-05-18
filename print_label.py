#!/usr/bin/env python3
"""
Print shipping label PDFs on the Beeprt / JADENS JD-268BT 4x6 thermal printer.

Usage:
    python3 print_label.py <file.pdf>

Classes:
    LabelPDF     - crops a letter-size PDF down to just the label content area
    LabelPrinter - sends a PDF to the CUPS printer
"""

import sys
import subprocess
import tempfile
import os
from pathlib import Path
from PIL import Image
import numpy as np

# ── Printer config ────────────────────────────────────────────────────────────
CUPS_PRINTER    = "beeprt"
PRINTER_DPI     = 203
LABEL_W_IN      = 4.0
LABEL_H_IN      = 6.0
LABEL_W_PTS     = LABEL_W_IN * 72   # 288 pts
LABEL_H_PTS     = LABEL_H_IN * 72   # 432 pts
DETECT_DPI      = 72    # low-res render just for content detection
PADDING_PTS     = 6     # whitespace to keep around detected content
MAX_MARGIN_PTS  = 36    # 0.5 inch — max allowed margin on any single side


class ExcessiveMarginError(ValueError):
    """Raised when the generated PDF has too much whitespace on any side."""
    pass


class LabelPDF:
    """
    Prepares a label PDF for printing.

    For PDFs that are already ~4x6 inches, passes through unchanged.
    For letter-size PDFs (USPS, Mercari, eBay etc.) that contain the label
    in one half of the page, auto-detects and crops to the label content area,
    outputting a properly sized vector PDF.
    """

    # If the page is within this margin of 4x6, treat it as already correct
    SIZE_TOLERANCE_PTS = 36   # 0.5 inch

    def __init__(self, pdf_path: str):
        self.source = Path(pdf_path)
        if not self.source.exists():
            raise FileNotFoundError(pdf_path)
        self._cropped_tmp: str | None = None

    def _page_size_pts(self) -> tuple[float, float]:
        """Return (width, height) of first page in points."""
        info = subprocess.run(["pdfinfo", str(self.source)],
                               capture_output=True, text=True).stdout
        for line in info.splitlines():
            if line.startswith("Page size:"):
                parts = line.split()
                return float(parts[2]), float(parts[4])
        return 612.0, 792.0  # letter fallback

    def _needs_crop(self, w_pts: float, h_pts: float) -> bool:
        tol = self.SIZE_TOLERANCE_PTS
        return not (
            abs(w_pts - LABEL_W_PTS) < tol and abs(h_pts - LABEL_H_PTS) < tol
            or
            abs(w_pts - LABEL_H_PTS) < tol and abs(h_pts - LABEL_W_PTS) < tol
        )

    def _detect_bbox_pts(self) -> tuple[float, float, float, float]:
        """Render at 72 DPI, find non-white content, return bbox in PDF points."""
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        subprocess.run([
            "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
            f"-r{DETECT_DPI}", f"-sOutputFile={tmp}", str(self.source),
        ], check=True, capture_output=True)
        img = Image.open(tmp).convert("RGB")
        os.unlink(tmp)

        arr = np.array(img)
        mask = (arr < 245).any(axis=2)
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]

        pad = PADDING_PTS  # at 72 DPI, 1px ≈ 1pt
        left   = max(0,          cols[0]  - pad)
        top    = max(0,          rows[0]  - pad)
        right  = min(img.width,  cols[-1] + pad)
        bottom = min(img.height, rows[-1] + pad)

        # Convert image top-down coords → PDF bottom-up coords
        page_h = img.height
        return float(left), float(page_h - bottom), float(right), float(page_h - top)

    def _crop_to_bbox(self, l: float, b: float, r: float, t: float) -> str:
        """
        Produce a portrait 4x6 vector PDF from the detected content bbox.

        Uses pypdf to set the page MediaBox/CropBox to the content area, then
        gs -dPDFFitPage to scale to fit.  Landscape content gets /Rotate 90 so
        it displays and prints as portrait.
        """
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import RectangleObject

        # Step 1 — crop page to content area via pypdf MediaBox/CropBox
        reader = PdfReader(str(self.source))
        writer = PdfWriter()
        page = reader.pages[0]
        page.mediabox = RectangleObject((l, b, r, t))
        page.cropbox  = RectangleObject((l, b, r, t))
        writer.add_page(page)
        tmp_cropped = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
        with open(tmp_cropped, "wb") as f:
            writer.write(f)

        # Step 2 — scale to fit landscape 4x6 device; rotate 90° for portrait display
        cw, ch = r - l, t - b
        landscape = cw > ch
        dev_w = LABEL_H_PTS if landscape else LABEL_W_PTS  # 432 or 288
        dev_h = LABEL_W_PTS if landscape else LABEL_H_PTS  # 288 or 432
        rotate_cmd = "[{ThisPage} << /Rotate 90 >> /PUT pdfmark" if landscape else ""

        out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
        cmd = [
            "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
            f"-dDEVICEWIDTHPOINTS={dev_w:.1f}",
            f"-dDEVICEHEIGHTPOINTS={dev_h:.1f}",
            "-dFIXEDMEDIA", "-dPDFFitPage",
            "-dCompatibilityLevel=1.4",
            f"-sOutputFile={out}",
        ]
        if rotate_cmd:
            cmd += ["-c", rotate_cmd, "-f", tmp_cropped]
        else:
            cmd += [tmp_cropped]

        subprocess.run(cmd, check=True, capture_output=True)
        os.unlink(tmp_cropped)
        return out

    def _render_to_image(self, pdf_path: str) -> Image.Image:
        """Render first page of a PDF at DETECT_DPI and return as RGB image."""
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        subprocess.run([
            "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
            f"-r{DETECT_DPI}", f"-sOutputFile={tmp}", pdf_path,
        ], check=True, capture_output=True)
        img = Image.open(tmp).convert("RGB")
        os.unlink(tmp)
        return img

    def validate(self, pdf_path: str) -> dict:
        """
        Render the PDF and verify no side has excessive whitespace.

        Returns a dict with margin measurements (in pts) for all four sides.
        Raises ExcessiveMarginError if any margin exceeds MAX_MARGIN_PTS.
        """
        img = self._render_to_image(pdf_path)
        arr = np.array(img)
        mask = (arr < 245).any(axis=2)
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]

        if rows.size == 0 or cols.size == 0:
            raise ExcessiveMarginError("Output PDF appears to be blank")

        # At DETECT_DPI=72, 1 pixel ≈ 1 pt
        margins = {
            "left":   float(cols[0]),
            "right":  float(img.width  - 1 - cols[-1]),
            "top":    float(rows[0]),
            "bottom": float(img.height - 1 - rows[-1]),
        }

        excessive = {side: pts for side, pts in margins.items()
                     if pts > MAX_MARGIN_PTS}
        if excessive:
            details = ", ".join(f"{s}={v:.1f}pts ({v/72:.2f}\")"
                                for s, v in excessive.items())
            raise ExcessiveMarginError(
                f"Output PDF has excessive margin — {details} "
                f"(max allowed: {MAX_MARGIN_PTS}pts / {MAX_MARGIN_PTS/72:.2f}\")"
            )

        return margins

    def prepare(self) -> str:
        """
        Return path to a validated, print-ready PDF.
        If cropping was needed, returns a temp file (cleaned up on close()).
        Otherwise returns the original path.
        Raises ExcessiveMarginError if the output has too much whitespace.
        """
        w, h = self._page_size_pts()
        print(f"  Source page: {w/72:.2f}\" x {h/72:.2f}\"")

        if not self._needs_crop(w, h):
            print("  Already label-sized, no crop needed.")
            result = str(self.source)
        else:
            print("  Letter-size detected — auto-cropping to label content ...")
            l, b, r, t = self._detect_bbox_pts()
            print(f"  Content bbox: {(r-l)/72:.2f}\" x {(t-b)/72:.2f}\"")
            self._cropped_tmp = self._crop_to_bbox(l, b, r, t)
            result = self._cropped_tmp

        margins = self.validate(result)
        print(f"  Margins (pts) — "
              f"L:{margins['left']:.0f} R:{margins['right']:.0f} "
              f"T:{margins['top']:.0f} B:{margins['bottom']:.0f}")
        return result

    def close(self):
        if self._cropped_tmp and os.path.exists(self._cropped_tmp):
            os.unlink(self._cropped_tmp)
            self._cropped_tmp = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class LabelPrinter:
    """
    Sends a PDF to the Beeprt/JADENS CUPS printer.
    """

    def __init__(self, printer: str = CUPS_PRINTER):
        self.printer = printer

    def print(self, pdf_path: str):
        print(f"  Sending to {self.printer} ...")
        subprocess.run([
            "lp", "-d", self.printer,
            "-o", f"media=Custom.{LABEL_W_IN}x{LABEL_H_IN}in",
            "-o", "roRotate=0",
            pdf_path,
        ], check=True)
        print("  Done.")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    printer = LabelPrinter()

    with LabelPDF(pdf_path) as label:
        ready = label.prepare()
        printer.print(ready)


if __name__ == "__main__":
    main()

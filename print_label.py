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
        """Use ghostscript to produce a cropped vector PDF."""
        w = r - l
        h = t - b
        out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
        subprocess.run([
            "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
            f"-dDEVICEWIDTHPOINTS={w:.1f}",
            f"-dDEVICEHEIGHTPOINTS={h:.1f}",
            "-dFIXEDMEDIA",
            "-dCompatibilityLevel=1.4",
            f"-sOutputFile={out}",
            "-c", f"<</BeginPage {{ {l:.1f} neg {b:.1f} neg translate }}>> setpagedevice",
            "-f", str(self.source),
        ], check=True, capture_output=True)
        return out

    def prepare(self) -> str:
        """
        Return path to a print-ready PDF.
        If cropping was needed, returns a temp file (cleaned up on close()).
        Otherwise returns the original path.
        """
        w, h = self._page_size_pts()
        print(f"  Source page: {w/72:.2f}\" x {h/72:.2f}\"")

        if not self._needs_crop(w, h):
            print("  Already label-sized, no crop needed.")
            return str(self.source)

        print("  Letter-size detected — auto-cropping to label content ...")
        l, b, r, t = self._detect_bbox_pts()
        print(f"  Content bbox: {(r-l)/72:.2f}\" x {(t-b)/72:.2f}\"")
        self._cropped_tmp = self._crop_to_bbox(l, b, r, t)
        return self._cropped_tmp

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

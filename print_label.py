#!/usr/bin/env python3
"""
Print a shipping label PDF on the Beeprt 4x6 thermal printer.
Works with letter-size PDFs where the label is in the top/bottom half.

Usage: python3 print_label.py <file.pdf>
"""

import sys
import subprocess
import tempfile
import os
from pathlib import Path
from PIL import Image
import numpy as np

CUPS_PRINTER = "beeprt"
PRINTER_DPI  = 203
RENDER_DPI   = 406   # render at 2x then downsample for quality
PADDING_PX   = 20    # scaled with render DPI
# Final label size in pixels at printer DPI (portrait: 4" x 6")
LABEL_W_PX   = 4 * PRINTER_DPI   # 812
LABEL_H_PX   = 6 * PRINTER_DPI   # 1218


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"Processing {pdf_path} ...")

    # Render PDF at 2x DPI for quality downsampling
    tmp_full = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    subprocess.run([
        "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
        f"-r{RENDER_DPI}", f"-sOutputFile={tmp_full}", pdf_path,
    ], check=True, capture_output=True)

    img = Image.open(tmp_full).convert("RGB")
    os.unlink(tmp_full)

    # Auto-crop to label content
    arr = np.array(img)
    mask = (arr < 245).any(axis=2)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    bbox = (
        max(0,          cols[0]  - PADDING_PX),
        max(0,          rows[0]  - PADDING_PX),
        min(img.width,  cols[-1] + PADDING_PX),
        min(img.height, rows[-1] + PADDING_PX),
    )
    cropped = img.crop(bbox)

    # Rotate 90° CW to portrait feed orientation
    rotated = cropped.rotate(-90, expand=True)

    # Scale to exact printer resolution — no CUPS-side resampling needed
    rotated.thumbnail((LABEL_W_PX, LABEL_H_PX), Image.LANCZOS)
    canvas = Image.new("RGB", (LABEL_W_PX, LABEL_H_PX), (255, 255, 255))
    canvas.paste(rotated, ((LABEL_W_PX - rotated.width) // 2,
                           (LABEL_H_PX - rotated.height) // 2))
    print(f"Output: {canvas.width}x{canvas.height}px  "
          f"({canvas.width/PRINTER_DPI:.2f}\" x {canvas.height/PRINTER_DPI:.2f}\" at {PRINTER_DPI}dpi)")

    tmp_out = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    canvas.save(tmp_out, dpi=(PRINTER_DPI, PRINTER_DPI))

    print("Sending to printer ...")
    subprocess.run([
        "lp", "-d", CUPS_PRINTER,
        "-o", "media=Custom.4x6in",
        "-o", "roRotate=0",
        tmp_out,
    ], check=True)
    os.unlink(tmp_out)
    print("Done.")


if __name__ == "__main__":
    main()

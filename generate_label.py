#!/usr/bin/env python3
"""
Generate a print-ready 4x6 vector PDF from a shipping label PDF.
Does NOT print — use print_label.py for printing.

Usage:
    python3 generate_label.py <input.pdf>
    python3 generate_label.py <input.pdf> <output.pdf>

Output defaults to <input>_4x6.pdf in the same directory.
"""

import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from print_label import LabelPDF, ExcessiveMarginError


def generate(input_path: str, output_path: str | None = None) -> str:
    inp = Path(input_path)
    out = Path(output_path) if output_path else inp.with_stem(inp.stem + "_4x6")

    print(f"Input:  {inp}")
    with LabelPDF(str(inp)) as label:
        ready = label.prepare()
        shutil.copy2(ready, out)

    print(f"Output: {out}")
    return str(out)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.pdf> [output.pdf]")
        sys.exit(1)

    input_path  = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        generate(input_path, output_path)
    except FileNotFoundError as e:
        print(f"Error: file not found — {e}")
        sys.exit(1)
    except ExcessiveMarginError as e:
        print(f"Validation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

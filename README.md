# JADENS / Beeprt Thermal Label Printer on Linux

Print shipping labels from PDFs on a **JADENS JD-268BT** (Beeprt) 4×6 thermal label printer using Linux. Works with letter-size PDFs that contain a label in the upper or lower half of the page — the common format produced by USPS, Mercari, eBay, and similar platforms.

---

## Hardware

- **Printer:** JADENS JD-268BT (also sold as Beeprt LabelPrinter)
- **USB IDs:** `09c6:0426`
- **Label size:** 4" × 6" (102mm × 152mm)
- **Print resolution:** 203 DPI

---

## Requirements

### System

- Ubuntu 22.04+ (or any Debian-based Linux with CUPS)
- Python 3.10+
- Ghostscript (`gs`)

```bash
sudo apt install cups ghostscript python3-pip
```

### Python packages

```bash
pip3 install pillow numpy
```

### CUPS driver

This printer requires the Rollo CUPS driver (`rastertorollo`), which handles the TSPL raster conversion. The Beeprt and Rollo printers share the same hardware family.

```bash
curl -H "Referer: https://www.rollo.com/driver-linux/" \
  "https://rollo-main.b-cdn.net/driver-dl/linux/rollo-cups-driver_1.8.4-1_amd64.deb" \
  -o rollo-cups-driver.deb
sudo apt install ./rollo-cups-driver.deb
```

---

## Setup

### 1. Add the printer to CUPS

Plug in the printer via USB, then:

```bash
sudo lpadmin -p beeprt \
  -v "usb://JADENS/JD-268BT?serial=<YOUR_SERIAL>" \
  -P /usr/share/cups/model/rollo-x1038.ppd \
  -E
```

Find your serial number with:

```bash
lsusb -v -d 09c6:0426 2>/dev/null | grep iSerial
```

Or let CUPS auto-detect:

```bash
lpinfo -v | grep -i jadens
```

### 2. Verify the printer is ready

```bash
lpstat -p beeprt
```

---

## Usage

```bash
python3 print_label.py <label.pdf>
```

### Example

```bash
python3 print_label.py ~/Downloads/usps_label.pdf
```

### What it does

1. Renders the PDF at 406 DPI (2× printer resolution) using Ghostscript
2. Auto-detects and crops the label content area, ignoring whitespace
3. Rotates 90° CW to match the printer's feed orientation
4. Downsamples to exactly **812×1218 px** (203 DPI × 4"×6") using Lanczos
5. Sends the PNG to CUPS — no driver-side resampling, full native resolution

---

## Troubleshooting

### Job stuck as "active" in CUPS queue

This was a major pain point. The USB backend waits indefinitely for a bidirectional status response the printer never sends. The Rollo PPD driver resolves this — do not use a raw queue with the USB backend.

```bash
# Cancel all stuck jobs
cancel -a beeprt
```

### "Resource busy" error with pyusb / python-escpos

CUPS holds the USB device. Do not use `python-escpos` directly — route through CUPS instead.

### Printer not detected after power cycle

```bash
sudo systemctl restart cups
lpinfo -v | grep -i jadens
```

### Nothing prints (silent failure)

Enable CUPS debug logging to see what's happening:

```bash
sudo cupsctl --debug-logging
sudo tail -f /var/log/cups/error_log
```

---

## How it was figured out

Getting this printer working on Linux required several non-obvious steps:

- **ESC/POS doesn't work** — despite being a thermal printer, this hardware uses TSPL (TSC Scripting Language), not ESC/POS
- **Raw CUPS queues get stuck** — the printer doesn't send bidirectional USB status responses, so CUPS hangs waiting
- **The fix is the Rollo driver** — Rollo and JADENS/Beeprt are the same OEM hardware; the Rollo Linux CUPS driver (`rastertorollo`) handles the TSPL raster conversion and solves the bidirectional timeout
- **Print quality** — rendering at 2× DPI and pre-scaling with Lanczos before sending produces sharper output than relying on CUPS `fit-to-page` resampling

---

## License

MIT

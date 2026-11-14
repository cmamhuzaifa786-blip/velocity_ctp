"""Code 128 (code set B) barcodes rendered as inline SVG.

Pure Python, no external libraries or CDNs, so tickets print the same in the browser and in PDFs.
"""

from __future__ import annotations

from html import escape

# Bar/space widths for symbol values 0-106 (ISO/IEC 15417). 106 is the stop pattern (7 elements).
PATTERNS = (
	"212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
	"221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
	"221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
	"212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
	"231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
	"231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
	"314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
	"112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
	"111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
	"214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
	"114131", "311141", "411131", "211412", "211214", "211232", "2331112",
)  # fmt: skip
START_B = 104
STOP = 106
QUIET_ZONE = 10  # modules on each side


def encode(value: str) -> list[int]:
	"""Symbol values for `value` in code set B, including start, check and stop symbols."""
	if not value:
		raise ValueError("Cannot encode an empty barcode value.")
	codes = [START_B]
	for char in value:
		code = ord(char) - 32
		if not 0 <= code <= 95:
			raise ValueError(f"Character {char!r} cannot be encoded in Code 128 set B.")
		codes.append(code)
	checksum = (START_B + sum(position * code for position, code in enumerate(codes[1:], start=1))) % 103
	return [*codes, checksum, STOP]


def modules(value: str) -> str:
	"""Binary module string ("1" = bar, "0" = space) for `value`."""
	bits = []
	for code in encode(value):
		for index, width in enumerate(PATTERNS[code]):
			bits.append(("1" if index % 2 == 0 else "0") * int(width))
	return "".join(bits)


def svg(value: str, height: int = 40, module_width: float = 1.0, show_text: bool = False) -> str:
	"""Inline SVG of the barcode. It scales to its container width; height is in the same units."""
	bits = modules(value)
	total = len(bits) + 2 * QUIET_ZONE
	rects = []
	x = QUIET_ZONE
	run = 0
	for i, bit in enumerate(bits + "0"):
		if bit == "1":
			run += 1
			continue
		if run:
			start = x + i - run
			rects.append(
				f'<rect x="{start * module_width:g}" y="0" width="{run * module_width:g}" height="{height}"/>'
			)
			run = 0
	text_height = 12 if show_text else 0
	text = (
		f'<text x="{total * module_width / 2:g}" y="{height + text_height - 1}" text-anchor="middle" '
		f'font-family="monospace" font-size="10">{escape(value)}</text>'
		if show_text
		else ""
	)
	return (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total * module_width:g} {height + text_height}" '
		f'preserveAspectRatio="none" shape-rendering="crispEdges" role="img" aria-label="{escape(value)}">'
		f'<rect width="100%" height="100%" fill="#fff"/><g fill="#000">{"".join(rects)}</g>{text}</svg>'
	)

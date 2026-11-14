"""Code 128 encoder test. The expected module strings were produced by JsBarcode (CODE128B),
the barcode library Frappe ships, so the tickets scan exactly like Frappe's own barcodes.

Run: ../../env/bin/python -m unittest velocity_ctp.tests.test_code128   (from apps/velocity_ctp)
"""

import unittest

from velocity_ctp.cutting import code128

JSBARCODE_CODE128B = {
	"BDL-0000001": (
		"110100100001000101100010110001000100011011101001101110010011101100100111011001001110110010011101100100111011001001110110010011100110100101100001100011101011"
	),
	"BDL-0000123": (
		"110100100001000101100010110001000100011011101001101110010011101100100111011001001110110010011101100100111001101100111001011001011100100110111001100011101011"
	),
	"STJ-0001/26": (
		"110100100001101110100011011100010101101110001001101110010011101100100111011001001110110010011100110101110011001100111001011001110100100011110101100011101011"
	),
}


class TestCode128(unittest.TestCase):
	def test_matches_jsbarcode(self):
		for value, expected in JSBARCODE_CODE128B.items():
			self.assertEqual(code128.modules(value), expected, value)

	def test_svg_has_bars_and_label(self):
		svg = code128.svg("BDL-0000001", show_text=True)
		self.assertTrue(svg.startswith("<svg") and svg.count("<rect") > 20 and "BDL-0000001" in svg)

	def test_rejects_unsupported_characters(self):
		with self.assertRaises(ValueError):
			code128.encode("é")


if __name__ == "__main__":
	unittest.main()

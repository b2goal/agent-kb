import unittest

from shopdemo.catalog import sku


class SkuTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(sku.normalize(" tea-0001 "), "TEA-0001")
        with self.assertRaises(ValueError):
            sku.normalize("TEA1")

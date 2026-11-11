import unittest
import pandas as pd
from brand_identity import identify_brand


class BrandIdentityTests(unittest.TestCase):
    def setUp(self):
        self.base = pd.DataFrame({"codigo": ["203044", "949189"]})

    def test_identifies_sales_brand_by_code(self):
        raw = pd.DataFrame({"Codigo": [203044, 949189]})
        sales = pd.DataFrame({"Codigo": [949189, 203044], "Marca": ["ASX", "ASX"]})
        self.assertEqual(identify_brand(self.base, raw, sales), ("ASX", 2, 2, "Vendas Produtos"))

    def test_does_not_invent_brand_from_filename_or_line(self):
        raw = pd.DataFrame({"Codigo": [203044], "Nome": ["LINHA PESADA"]})
        self.assertEqual(identify_brand(self.base, raw, None)[0], None)

    def test_rejects_multi_brand_mix(self):
        sales = pd.DataFrame({"Codigo": [203044, 949189], "Marca": ["ASX", "VOX"]})
        with self.assertRaisesRegex(ValueError, "mais de uma marca"):
            identify_brand(self.base, pd.DataFrame(), sales)

    def test_rejects_code_brand_conflicts(self):
        raw = pd.DataFrame({"Codigo": [203044], "Marca": ["ASX"]})
        sales = pd.DataFrame({"Codigo": [203044], "Marca": ["VOX"]})
        with self.assertRaisesRegex(ValueError, "divergente"):
            identify_brand(self.base, raw, sales)

    def test_partial_identification_is_not_presented_as_complete(self):
        sales = pd.DataFrame({"Codigo": [203044], "Marca": ["ASX"]})
        self.assertEqual(identify_brand(self.base, pd.DataFrame(), sales)[:3], ("ASX", 1, 2))


if __name__ == "__main__":
    unittest.main()

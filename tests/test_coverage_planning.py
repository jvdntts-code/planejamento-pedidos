import unittest

import pandas as pd

from coverage_planning import build_coverage_plan, make_abc_snapshot


def source_products():
    return pd.DataFrame([
        {
            "codigo": "101", "curva_abc": "A", "preco_venda": 20,
            "vendas_periodo": 100, "preco_venda_origem": "Vendas Produtos",
        },
        {
            "codigo": "202", "curva_abc": "C", "preco_venda": 10,
            "vendas_periodo": 30, "preco_venda_origem": "Vendas Produtos",
        },
        {
            "codigo": "303", "curva_abc": "B", "preco_venda": 15,
            "vendas_periodo": 20, "preco_venda_origem": "Vendas Produtos",
        },
    ])


def report():
    return pd.DataFrame([
        {"codigo": "101", "referencia": "AA", "descricao": "Peça A", "marca": "VOX",
         "emb_compra": 6, "estoque_M20": 10},
        {"codigo": "202", "referencia": "BB", "descricao": "Peça C", "marca": "VOX",
         "emb_compra": 1, "estoque_M20": 20},
        {"codigo": "303", "referencia": "CC", "descricao": "Peça B", "marca": "OUTRA",
         "emb_compra": 1, "estoque_M20": 0},
    ])


def branches():
    return pd.DataFrame([
        {
            "Codigo": "101", "Filial": "M01",
            "Considerada na Necessidade de Compra": "Sim",
            "Estoque Atual": 20, "Vendas 90d": 90,
        },
        {
            "Codigo": "101", "Filial": "M11",
            "Considerada na Necessidade de Compra": "Sim",
            "Estoque Atual": 100, "Vendas 90d": 90,
        },
        {
            "Codigo": "101", "Filial": "M25",
            "Considerada na Necessidade de Compra": "Não",
            "Estoque Atual": 0, "Vendas 90d": 900,
        },
        {
            "Codigo": "202", "Filial": "M01",
            "Considerada na Necessidade de Compra": "Sim",
            "Estoque Atual": 15, "Vendas 90d": 0,
        },
        {
            "Codigo": "303", "Filial": "M01",
            "Considerada na Necessidade de Compra": "Sim",
            "Estoque Atual": 0, "Vendas 90d": 90,
        },
    ])


class CoverageByCurveTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_abc_snapshot(source_products(), "VOX", 90)

    def test_defaults_and_leadtime_do_not_double_count(self):
        result = build_coverage_plan(
            report(), branches(), self.snapshot,
            {"A": 90, "B": 60, "C": 30}, leadtime_days=30
        )
        row = result[result["Código"].eq("101")].iloc[0]
        # Loja 1: 1 un/dia × (90+30) - 20 = 100.
        # Loja 2: 1 un/dia × (90+30) - 100 = 20.
        # M20: 10 unidades, uma única vez. 110 / emb. 6 => 114.
        self.assertEqual(row["Necessidade bruta filiais"], 120.0)
        self.assertEqual(row["Saldo a comprar antes da embalagem"], 110.0)
        self.assertEqual(row["Quantidade simulada"], 114)
        self.assertEqual(row["Meta (dias)"], 90)
        self.assertEqual(row["Vendas 90d filiais"], 180)

    def test_optional_pending_only_when_explicit(self):
        none = build_coverage_plan(
            report(), branches(), self.snapshot,
            {"A": 90, "B": 60, "C": 30}, 30,
            pend_by_code={"101": 35}, include_pending=False,
        )
        yes = build_coverage_plan(
            report(), branches(), self.snapshot,
            {"A": 90, "B": 60, "C": 30}, 30,
            pend_by_code={"101": 35}, include_pending=True,
        )
        self.assertEqual(none.iloc[0]["Quantidade simulada"], 114)
        self.assertEqual(yes.iloc[0]["Quantidade simulada"], 78)

    def test_without_sales_does_not_create_order(self):
        result = build_coverage_plan(
            report(), branches(), self.snapshot,
            {"A": 90, "B": 60, "C": 30}, 35,
        )
        item = result[result["Código"].eq("202")].iloc[0]
        self.assertEqual(item["Quantidade simulada"], 0)
        self.assertIn("SEM VENDAS", item["Situação"])

    def test_other_brand_never_inherits_curve(self):
        result = build_coverage_plan(
            report(), branches(), self.snapshot,
            {"A": 90, "B": 60, "C": 30}, 0,
        )
        item = result[result["Código"].eq("303")].iloc[0]
        self.assertEqual(item["Situação"], "SEM CURVA ABC VERIFICADA")
        self.assertTrue(pd.isna(item["Quantidade simulada"]))

    def test_missing_abc_is_not_assigned_C(self):
        snap = dict(self.snapshot)
        snap["curves"] = {"101": "A"}
        result = build_coverage_plan(
            report(), branches(), snap, {"A": 90, "B": 60, "C": 30}, 0
        )
        item = result[result["Código"].eq("202")].iloc[0]
        self.assertEqual(item["Curva ABC"], "Não identificada")
        self.assertTrue(pd.isna(item["Quantidade simulada"]))

    def test_invalid_stock_blocks_quote(self):
        bad = report()
        bad.loc[0, "estoque_M20"] = -1
        result = build_coverage_plan(
            bad, branches(), self.snapshot, {"A": 90, "B": 60, "C": 30}, 30
        )
        self.assertIn("CONFERIR", result.iloc[0]["Situação"])
        self.assertTrue(pd.isna(result.iloc[0]["Quantidade simulada"]))

    def test_unverified_financial_data_blocks_scenario(self):
        bad = source_products()
        bad.loc[0, "preco_venda_origem"] = "Preço de custo usado provisoriamente"
        snapshot = make_abc_snapshot(bad, "VOX", 90)
        self.assertFalse(snapshot["reliable_prices"])
        with self.assertRaisesRegex(ValueError, "não é confiável"):
            build_coverage_plan(
                report(), branches(), snapshot, {"A": 90, "B": 60, "C": 30}, 0
            )

    def test_duplicate_product_code_blocks_purchase(self):
        duplicate = pd.concat([report(), report().iloc[[0]]], ignore_index=True)
        result = build_coverage_plan(
            duplicate, branches(), self.snapshot, {"A": 90, "B": 60, "C": 30}, 30
        )
        self.assertTrue(
            result[result["Código"].eq("101")]["Situação"]
            .str.contains("DUPLICADO").all()
        )

    def test_invalid_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            build_coverage_plan(
                report(), branches(), self.snapshot,
                {"A": 90, "B": 60, "C": 0}, 10
            )


if __name__ == "__main__":
    unittest.main()

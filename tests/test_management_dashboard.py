import unittest
import pandas as pd
from management_dashboard import build_management_snapshot, build_decision_center


def sample():
    return pd.DataFrame([
        dict(codigo="1", descricao="A", linha="L1", curva_abc="A",
             status="RUPTURA", estoque=0, vendas_periodo=60,
             faturamento_periodo=600, valor_estoque=0, cobertura_dias=0),
        dict(codigo="2", descricao="B", linha="L1", curva_abc="B",
             status="ALTO", estoque=100, vendas_periodo=10,
             faturamento_periodo=100, valor_estoque=1000, cobertura_dias=900),
        dict(codigo="3", descricao="C", linha="L2", curva_abc="C",
             status="SEM VENDA - ESTOQUE PARADO", estoque=25, vendas_periodo=0,
             faturamento_periodo=0, valor_estoque=250, cobertura_dias=float("nan")),
    ])


class DashboardTests(unittest.TestCase):
    def test_metrics_come_from_products(self):
        result = build_management_snapshot(sample(), 30)
        self.assertEqual(result["items"], 3)
        self.assertEqual(result["revenue"], 700)
        self.assertEqual(result["urgency_ab"], 1)
        self.assertEqual(result["high_count"], 1)
        self.assertEqual(result["idle_count"], 1)
        self.assertEqual(result["idle_units"], 25)
        self.assertAlmostEqual(result["coverage_months"], 100 / (70 / 30) / 30)
        self.assertEqual(result["top_attention"].iloc[0]["codigo"], "1")

    def test_no_sales_has_no_fictitious_coverage(self):
        df = sample().iloc[[2]].copy()
        result = build_management_snapshot(df, 90)
        self.assertIsNone(result["coverage_months"])
        self.assertEqual(result["urgency_ab"], 0)
        self.assertEqual(result["idle_count"], 1)

    def test_nonpositive_period_fails(self):
        with self.assertRaises(ValueError):
            build_management_snapshot(sample(), 0)


    def test_decisions_use_existing_status_and_do_not_create_orders(self):
        result = build_decision_center(sample(), 30)
        self.assertEqual(result["availability"]["codigo"].tolist(), ["1"])
        self.assertEqual(result["availability_ab"], 1)
        self.assertEqual(result["review"]["codigo"].tolist(), ["3", "2"])
        self.assertEqual(result["review_units"], 125)
        self.assertEqual(len(result["quality"]), 0)
        self.assertIn("Sem vendas em 30 dias", result["review"].iloc[0]["Motivo"])

    def test_data_issues_are_explained_by_product(self):
        df = sample().copy()
        df["preco_venda"] = [10, 0, 10]
        df["preco_venda_origem"] = [
            "Vendas Produtos", "Preço de custo usado provisoriamente", "Vendas Produtos"
        ]
        df.loc[2, "estoque"] = -2
        df.loc[2, "codigo"] = "1"
        result = build_decision_center(df, 90)
        reasons = result["quality"]["Motivo"].tolist()
        self.assertEqual(len(result["quality"]), 3)
        self.assertTrue(any("Sem preço de venda válido" in x for x in reasons))
        self.assertTrue(any("Preço de custo usado" in x for x in reasons))
        self.assertTrue(any("Estoque negativo" in x for x in reasons))
        self.assertTrue(any("Código repetido" in x for x in reasons))

    def test_risk_order_prioritizes_rupture_not_revenue(self):
        df = sample().copy()
        df.loc[1, "status"] = "RISCO DE RUPTURA"
        df.loc[1, "faturamento_periodo"] = 99999
        result = build_decision_center(df, 90)
        self.assertEqual(result["availability"]["codigo"].tolist(), ["1", "2"])

    def test_zero_sales_never_generates_rupture_alert(self):
        df = sample().iloc[[2]].copy()
        df["status"] = "SEM VENDA - ESTOQUE PARADO"
        result = build_decision_center(df, 90)
        self.assertTrue(result["availability"].empty)
        self.assertEqual(len(result["review"]), 1)

    def test_no_price_column_is_not_automatically_an_error(self):
        df = sample().iloc[:1].copy()
        result = build_decision_center(df, 30)
        self.assertTrue(result["quality"].empty)

    def test_invalid_period_fails(self):
        with self.assertRaises(ValueError):
            build_decision_center(sample(), 0)


if __name__ == "__main__":
    unittest.main()

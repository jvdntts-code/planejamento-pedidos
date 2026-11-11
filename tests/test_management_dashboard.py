import unittest
import pandas as pd
from management_dashboard import build_management_snapshot


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


if __name__ == "__main__":
    unittest.main()

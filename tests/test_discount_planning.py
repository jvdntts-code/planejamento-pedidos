import unittest

import pandas as pd

from discount_planning import load_unit_costs, simulate_discount_negotiation


def make_plans():
    rows = [
        # code, curve, packaging, normal, expanded, daily, stores stock, M20, raw need
        ("101", "A", 12, 24, 36, 1.0, 0, 0, 18, 30),
        ("202", "B", 10, 20, 30, 2.0, 0, 0, 16, 25),
        ("303", "C", 5, 15, 15, 0.5, 0, 0, 14, 14),
    ]
    base, extra = [], []
    for code, curve, pack, normal, extended, daily, store, m20, raw, raw_ext in rows:
        record = {
            "Código": code,
            "Referência": "REF" + code,
            "Descrição": "Produto " + code,
            "Marca": "VOX",
            "Curva ABC": curve,
            "Vendas 90d filiais": daily * 90,
            "Estoque filiais consideradas": store,
            "Estoque M20": m20,
            "Lead time (dias)": 0,
            "Pendência considerada": 0,
            "Embalagem": float(pack),
            "Situação": "SIMULAÇÃO COM COMPRA",
        }
        norm = dict(record, **{
            "Meta (dias)": {"A": 90, "B": 60, "C": 30}[curve],
            "Saldo a comprar antes da embalagem": raw,
            "Quantidade simulada": normal,
        })
        expanded = dict(record, **{
            "Meta (dias)": {"A": 120, "B": 75, "C": 30}[curve],
            "Saldo a comprar antes da embalagem": raw_ext,
            "Quantidade simulada": extended,
        })
        base.append(norm)
        extra.append(expanded)
    return pd.DataFrame(base), pd.DataFrame(extra)


class DiscountPlanningTests(unittest.TestCase):
    def test_exact_threshold_enables_discount_only_at_100_percent(self):
        a, b = make_plans()
        result = simulate_discount_negotiation(
            a, b, limit_units=81, discount_pct=5,
            unit_costs={"101": 10, "202": 20, "303": 5},
        )
        self.assertTrue(result["discount_achieved"])
        self.assertEqual(result["normal_units"], 59)
        self.assertEqual(result["proposed_units"], 81)
        self.assertEqual(result["extra_units"], 22)
        financial = result["financial"]
        self.assertEqual(financial["Compra normal sem desconto (R$)"], 715.0)
        self.assertEqual(financial["Proposta antes do desconto (R$)"], 1035.0)
        self.assertEqual(financial["Desconto condicional (R$)"], 51.75)
        self.assertEqual(financial["Proposta após desconto (R$)"], 983.25)
        self.assertEqual(financial["Diferença de desembolso (R$)"], 268.25)

    def test_large_target_is_not_forced_and_discount_stays_inactive(self):
        a, b = make_plans()
        result = simulate_discount_negotiation(
            a, b, limit_units=34500, discount_pct=5,
            unit_costs={"101": 10, "202": 20, "303": 5},
        )
        self.assertEqual(result["proposed_units"], 81)
        self.assertEqual(result["remaining_units"], 34419)
        self.assertFalse(result["discount_achieved"])
        self.assertEqual(result["financial"]["Desconto condicional (R$)"], 0.0)

    def test_short_limit_prioritizes_A_and_no_extras_before_normal(self):
        a, b = make_plans()
        result = simulate_discount_negotiation(a, b, limit_units=50)
        table = result["table"].set_index("Código")
        self.assertEqual(table.at["101", "Compra proposta (peças)"], 24)
        self.assertEqual(table.at["202", "Compra proposta (peças)"], 20)
        self.assertEqual(table.at["303", "Compra proposta (peças)"], 5)
        self.assertEqual(result["proposed_units"], 49)
        self.assertEqual(result["remaining_units"], 1)
        self.assertEqual(result["extra_units"], 0)
        self.assertFalse(result["normal_fully_covered"])

    def test_extra_C_absent_without_extra_target(self):
        a, b = make_plans()
        result = simulate_discount_negotiation(a, b, limit_units=100)
        c = result["table"].set_index("Código").loc["303"]
        self.assertEqual(c["Peças extras para desconto"], 0)

    def test_excess_by_pack_visible(self):
        a, b = make_plans()
        result = simulate_discount_negotiation(a, b, limit_units=81)
        a_row = result["table"].set_index("Código").loc["101"]
        self.assertEqual(a_row["Excesso por embalagem (peças)"], 6)
        self.assertGreater(
            a_row["Cobertura proposta (dias)"], a_row["Teto negociação (dias)"]
            if a_row["Teto negociação (dias)"] < 36 else 0
        )

    def test_missing_costs_never_produce_fake_economy(self):
        a, b = make_plans()
        result = simulate_discount_negotiation(
            a, b, limit_units=81, unit_costs={"101": 10}
        )
        self.assertIsNone(result["financial"])
        self.assertEqual(result["missing_cost_codes"], ["202", "303"])

    def test_unclassified_item_does_not_receive_pieces(self):
        a, b = make_plans()
        a.at[0, "Curva ABC"] = "Não identificada"
        b.at[0, "Curva ABC"] = "Não identificada"
        result = simulate_discount_negotiation(a, b, limit_units=50)
        row = result["table"].set_index("Código").loc["101"]
        self.assertTrue(pd.isna(row["Compra proposta (peças)"]))
        self.assertEqual(row["Resultado"], "Fora da distribuição — conferir")

    def test_rejects_invalid_limits_and_mismatched_input(self):
        a, b = make_plans()
        with self.assertRaises(ValueError):
            simulate_discount_negotiation(a, b, 0)
        with self.assertRaises(ValueError):
            simulate_discount_negotiation(a, b.iloc[::-1].copy(), 100)
        with self.assertRaises(ValueError):
            simulate_discount_negotiation(a, b, 50, 100)

    def test_cost_file_parser_rejects_conflict_and_accepts_brl(self):
        raw = pd.DataFrame([
            {"Código": "101", "Custo Unitário": "R$ 12,50"},
            {"Código": "202", "Custo Unitário": 8.2},
        ])
        costs, invalid = load_unit_costs(raw)
        self.assertEqual(costs, {"101": 12.5, "202": 8.2})
        self.assertEqual(invalid, [])
        mixed = pd.concat(
            [raw, pd.DataFrame([{"Código": "101", "Custo Unitário": 20}])],
            ignore_index=True,
        )
        with self.assertRaisesRegex(ValueError, "divergente"):
            load_unit_costs(mixed)


if __name__ == "__main__":
    unittest.main()

import unittest

import pandas as pd

from discount_planning import (build_negotiation_inputs, load_unit_costs,
                               simulate_discount_negotiation)


def make_plan():
    # Dados totalmente fictícios, sem estoque ou custos reais no repositório.
    products = [
        # codigo, curva, embalagem, compra normal, consumo/dia, estoque das lojas, M20
        ("101", "A", 12, 24, 1.0, 0, 0, 18),
        ("202", "B", 10, 20, 2.0, 0, 0, 16),
        ("303", "C", 5, 15, 0.5, 0, 0, 14),
    ]
    result = []
    for code, curve, pack, regular, daily, stores, m20, raw_need in products:
        result.append({
            "Código": code,
            "Referência": "REF" + code,
            "Descrição": "Produto " + code,
            "Marca": "VOX",
            "Curva ABC": curve,
            "Vendas 90d filiais": daily * 90,
            "Estoque filiais consideradas": stores,
            "Estoque M20": m20,
            "Lead time (dias)": 0,
            "Pendência considerada": 0,
            "Embalagem": float(pack),
            "Situação": "SIMULAÇÃO COM COMPRA",
            "Meta (dias)": {"A": 90, "B": 60, "C": 30}[curve],
            "Saldo a comprar antes da embalagem": raw_need,
            "Quantidade simulada": regular,
        })
    return pd.DataFrame(result)


def new_item(code, curve, package, regular=0, daily=1, store=0, m20=0, lead=0):
    return {
        "Código": code, "Referência": "REF" + code,
        "Descrição": "Produto " + code, "Marca": "VOX",
        "Curva ABC": curve, "Vendas 90d filiais": daily * 90,
        "Estoque filiais consideradas": store, "Estoque M20": m20,
        "Lead time (dias)": lead, "Pendência considerada": 0,
        "Embalagem": float(package),
        "Situação": "SIMULAÇÃO COM COMPRA" if regular else "COBERTURA ATENDIDA",
        "Meta (dias)": {"A": 90, "B": 60, "C": 30}.get(curve, 30),
        "Saldo a comprar antes da embalagem": regular,
        "Quantidade simulada": regular,
    }


class DiscountPlanningTests(unittest.TestCase):
    def test_discount_requires_no_coverage_targets_or_normal_day_fields(self):
        plan = make_plan().drop(columns=[
            "Meta (dias)", "Saldo a comprar antes da embalagem"
        ])
        result = simulate_discount_negotiation(plan, limit_units=34500)
        self.assertEqual(result["proposed_units"], 34500)
        self.assertEqual(result["remaining_units"], 0)
        self.assertNotIn("Meta normal (dias)", result["table"].columns)
        self.assertNotIn("Dias acima da meta normal", result["table"].columns)
        self.assertIn("Cobertura proposta (dias)", result["table"].columns)

    def test_ignores_any_abc_day_targets_from_old_planner(self):
        a = make_plan()
        b = make_plan()
        a["Meta (dias)"] = [10, 10, 10]
        b["Meta (dias)"] = [1000, 1000, 1000]
        one = simulate_discount_negotiation(a, limit_units=100)["table"]
        other = simulate_discount_negotiation(b, limit_units=100)["table"]
        self.assertEqual(
            one["Compra proposta (peças)"].tolist(),
            other["Compra proposta (peças)"].tolist(),
        )

    def test_builds_purchase_input_from_existing_order_without_day_targets(self):
        base = pd.DataFrame([
            {"codigo": "101", "referencia": "AA", "descricao": "Peça A",
             "marca": "VOX", "emb_compra": 6, "estoque_M20": 10},
            {"codigo": "202", "referencia": "BB", "descricao": "Peça B",
             "marca": "VOX", "emb_compra": 2, "estoque_M20": 20},
        ])
        branches = pd.DataFrame([
            {"Codigo": "101", "Considerada na Necessidade de Compra": "Sim",
             "Estoque Atual": 30, "Vendas 90d": 90},
            {"Codigo": "101", "Considerada na Necessidade de Compra": "Não",
             "Estoque Atual": 1, "Vendas 90d": 900},
            {"Codigo": "202", "Considerada na Necessidade de Compra": "Sim",
             "Estoque Atual": 12, "Vendas 90d": 0},
        ])
        order = pd.DataFrame([
            {"Codigo": "101", "Necessidade Antes da Pendencia": 20},
            {"Codigo": "202", "Necessidade Antes da Pendencia": 4},
        ])
        snapshot = {"brand": "VOX", "source": "imported",
                    "curves": {"101": "A", "202": "B"}}
        plan = build_negotiation_inputs(
            base, branches, order, snapshot, leadtime_days=30,
            pending_by_code={"101": 8}, include_pending=True,
        )
        sku = plan.set_index("Código")
        self.assertEqual(sku.at["101", "Quantidade simulada"], 12)
        self.assertEqual(sku.at["101", "Pendência considerada"], 8)
        self.assertEqual(sku.at["101", "Vendas 90d filiais"], 90)
        self.assertEqual(sku.at["101", "Estoque filiais consideradas"], 30)
        self.assertEqual(sku.at["202", "Situação"],
                         "SEM VENDAS 90D NAS FILIAIS CONSIDERADAS")
        simulated = simulate_discount_negotiation(plan, limit_units=100)
        one = simulated["table"].set_index("Código").loc["101"]
        self.assertAlmostEqual(one["Cobertura atual (dias)"], 40)
        self.assertAlmostEqual(one["Cobertura na chegada (dias)"], 18)

    def test_no_confirmed_pendencies_are_not_counted_or_deducted(self):
        base = pd.DataFrame([{
            "codigo": "101", "referencia": "AA", "descricao": "Peça A",
            "marca": "VOX", "emb_compra": 6, "estoque_M20": 0
        }])
        stores = pd.DataFrame([{
            "Codigo": "101", "Considerada na Necessidade de Compra": "Sim",
            "Estoque Atual": 10, "Vendas 90d": 90
        }])
        order = pd.DataFrame([{
            "Codigo": "101", "Necessidade Antes da Pendencia": 20
        }])
        snapshot = {"brand": "VOX", "source": "imported",
                    "curves": {"101": "A"}}
        plan = build_negotiation_inputs(
            base, stores, order, snapshot, leadtime_days=0,
            pending_by_code={"101": 8}, include_pending=False,
        )
        self.assertEqual(plan.iloc[0]["Quantidade simulada"], 24)
        self.assertEqual(plan.iloc[0]["Pendência considerada"], 0)

    def test_exact_threshold_enables_discount_only_at_100_percent(self):
        normal = make_plan()
        result = simulate_discount_negotiation(
            normal, limit_units=81, discount_pct=5,
            unit_costs={"101": 10, "202": 20, "303": 5},
        )
        self.assertTrue(result["discount_achieved"])
        self.assertEqual(result["normal_units"], 59)
        self.assertEqual(result["proposed_units"], 81)
        self.assertEqual(result["extra_units"], 22)
        financial = result["financial"]
        self.assertEqual(financial["Compra normal sem desconto (R$)"], 715)
        self.assertEqual(financial["Proposta antes do desconto (R$)"], 1035)
        self.assertEqual(financial["Desconto condicional (R$)"], 51.75)
        self.assertEqual(financial["Proposta após desconto (R$)"], 983.25)
        self.assertEqual(financial["Diferença de desembolso (R$)"], 268.25)

    def test_target_34500_is_distributed_without_coverage_cap(self):
        result = simulate_discount_negotiation(make_plan(), limit_units=34500)
        self.assertEqual(result["proposed_units"], 34500)
        self.assertEqual(result["remaining_units"], 0)
        self.assertTrue(result["discount_achieved"])
        self.assertGreater(result["table"].iloc[0]["Cobertura proposta (dias)"], 365)
        self.assertGreater(result["above_365_skus"], 0)
        self.assertEqual(
            int(result["table"]["Compra proposta (peças)"].fillna(0).sum()), 34500
        )
        # Curva A primeiro, sem compra fictícia de produto C só para completar.
        self.assertGreater(
            result["table"].iloc[0]["Peças extras para desconto"], 0
        )

    def test_short_target_prioritizes_abc_with_no_extras(self):
        result = simulate_discount_negotiation(make_plan(), limit_units=50)
        by_code = result["table"].set_index("Código")
        self.assertEqual(by_code.at["101", "Compra proposta (peças)"], 24)
        self.assertEqual(by_code.at["202", "Compra proposta (peças)"], 20)
        self.assertEqual(by_code.at["303", "Compra proposta (peças)"], 5)
        self.assertEqual(result["proposed_units"], 49)
        self.assertEqual(result["remaining_units"], 1)
        self.assertEqual(result["extra_units"], 0)
        self.assertFalse(result["normal_fully_covered"])
        self.assertFalse(result["discount_achieved"])

    def test_distribution_spreads_across_similarly_covered_A_items(self):
        plan = pd.DataFrame([
            new_item("A1", "A", 10, regular=10),
            new_item("A2", "A", 10, regular=10),
            new_item("B1", "B", 10, regular=10),
        ])
        result = simulate_discount_negotiation(plan, limit_units=100)
        by_code = result["table"].set_index("Código")
        a1 = int(by_code.at["A1", "Compra proposta (peças)"])
        a2 = int(by_code.at["A2", "Compra proposta (peças)"])
        self.assertLessEqual(abs(a1 - a2), 10)
        self.assertEqual(by_code.at["B1", "Compra proposta (peças)"], 10)
        self.assertEqual(result["proposed_units"], 100)

    def test_exact_package_combination_prefers_reaching_goal(self):
        plan = pd.DataFrame([
            new_item("101", "A", 4),
            new_item("202", "B", 3),
        ])
        result = simulate_discount_negotiation(plan, limit_units=6)
        by_code = result["table"].set_index("Código")
        # 4+? não fecha 6. Duas embalagens de 3 fecham a meta sem exceder.
        self.assertEqual(by_code.at["101", "Compra proposta (peças)"], 0)
        self.assertEqual(by_code.at["202", "Compra proposta (peças)"], 6)
        self.assertTrue(result["discount_achieved"])

    def test_impossible_package_combination_reports_shortfall(self):
        plan = pd.DataFrame([
            new_item("101", "A", 4),
            new_item("202", "B", 6),
        ])
        result = simulate_discount_negotiation(plan, limit_units=5)
        self.assertEqual(result["proposed_units"], 4)
        self.assertEqual(result["remaining_units"], 1)
        self.assertFalse(result["discount_achieved"])

    def test_baseline_coverage_and_predicted_arrival(self):
        plan = pd.DataFrame([
            new_item("X1", "A", 10, regular=20, daily=2, store=90, m20=20, lead=30)
        ])
        result = simulate_discount_negotiation(plan, limit_units=30)
        item = result["table"].iloc[0]
        self.assertAlmostEqual(item["Cobertura atual (dias)"], 55)
        self.assertAlmostEqual(item["Cobertura na chegada (dias)"], 25)
        self.assertAlmostEqual(item["Cobertura compra normal (dias)"], 35)
        self.assertAlmostEqual(item["Cobertura proposta (dias)"], 40)
        self.assertEqual(item["Estoque projetado após compra (peças)"], 80)

    def test_zero_sales_excluded_from_discount_allocation(self):
        plan = pd.DataFrame([
            new_item("A1", "A", 1, daily=0),
            new_item("B1", "B", 2, daily=1),
        ])
        plan.loc[0, "Situação"] = "SEM VENDAS 90D NAS FILIAIS CONSIDERADAS"
        result = simulate_discount_negotiation(plan, limit_units=100)
        a = result["table"].set_index("Código").loc["A1"]
        self.assertTrue(pd.isna(a["Compra proposta (peças)"]))
        self.assertEqual(result["proposed_units"], 100)

    def test_missing_costs_never_produce_fake_economy(self):
        result = simulate_discount_negotiation(
            make_plan(), limit_units=81, unit_costs={"101": 10}
        )
        self.assertIsNone(result["financial"])
        self.assertEqual(result["missing_cost_codes"], ["202", "303"])

    def test_unclassified_and_duplicate_not_purchased(self):
        plan = pd.concat(
            [make_plan(), make_plan().iloc[[0]]], ignore_index=True
        )
        plan.loc[1, "Curva ABC"] = "Não identificada"
        result = simulate_discount_negotiation(plan, limit_units=100)
        by_code = result["table"]
        self.assertTrue(
            by_code[by_code["Código"].eq("101")]["Compra proposta (peças)"].isna().all()
        )
        self.assertTrue(
            by_code[by_code["Código"].eq("202")]["Compra proposta (peças)"].isna().all()
        )

    def test_reject_invalid_limits_or_missing_columns(self):
        plan = make_plan()
        for invalid in (0, -2, 1.5):
            with self.assertRaises(ValueError):
                simulate_discount_negotiation(plan, limit_units=invalid)
        with self.assertRaises(ValueError):
            simulate_discount_negotiation(plan, limit_units=81, discount_pct=100)
        with self.assertRaises(ValueError):
            simulate_discount_negotiation(plan.drop(columns=["Embalagem"]), 81)

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

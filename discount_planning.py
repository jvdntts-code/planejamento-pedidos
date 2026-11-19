"""Negociação por meta em peças: sem teto artificial de cobertura.

Primeiro atende necessidades normais por Curva ABC. Depois distribui
quantidades adicionais por A -> B -> C até tentar atingir a meta do
fornecedor. Dias de cobertura são resultados informativos da simulação.
"""
import math
import re
import unicodedata

import pandas as pd

from coverage_planning import product_key


CURVE_ORDER = {"A": 0, "B": 1, "C": 2}


def _number(value, default=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _header(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    return "".join(
        c for c in normalized.lower()
        if c.isalnum() and not unicodedata.combining(c)
    )


def _money(value):
    if isinstance(value, str):
        value = value.strip().replace("R$", "").replace(" ", "")
        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".") if (
                value.rfind(",") > value.rfind(".")
            ) else value.replace(",", "")
        elif "," in value:
            value = value.replace(",", ".")
    return _number(value)


def load_unit_costs(report):
    """Lê custo unitário por código; duplicatas divergentes são recusadas."""
    if report is None or report.empty:
        raise ValueError("Arquivo de custos vazio.")
    fields = {_header(col): col for col in report.columns}
    code_col = next(
        (fields[x] for x in ("codigo", "codigointerno", "codproduto") if x in fields),
        None,
    )
    cost_col = next(
        (fields[x] for x in (
            "custounitario", "precocusto", "custocompra", "precocompra",
            "custounitariocompra", "valordecusto",
        ) if x in fields),
        None,
    )
    if code_col is None or cost_col is None:
        raise ValueError(
            "Arquivo de custos precisa das colunas Código e Custo Unitário "
            "(ou Preço Custo)."
        )
    costs = {}
    invalid = []
    for _, record in report.iterrows():
        code = product_key(record[code_col])
        if not code:
            continue
        price = _money(record[cost_col])
        if price is None or price <= 0:
            invalid.append(code)
            continue
        if code in costs and not math.isclose(costs[code], price, rel_tol=1e-7):
            raise ValueError(f"Custo unitário divergente para o código {code}.")
        costs[code] = price
    if not costs:
        raise ValueError("Nenhum custo unitário positivo foi encontrado.")
    return costs, sorted(set(invalid))


def simulate_discount_negotiation(
    normal, limit_units=34500, discount_pct=5.0, unit_costs=None
):
    """Distribui uma META em peças sem teto de dias de cobertura.

    Primeiro atende às necessidades normais na ordem A/B/C. Se a meta
    permitir, reparte as unidades excedentes entre SKUs com vendas,
    equilibrando a cobertura relativa à meta *dentro da mesma curva*.
    Não limita a cobertura máxima: ela é resultado da simulação.
    Compra somente embalagens inteiras e nunca passa da meta informada.
    """
    if not isinstance(limit_units, int) or isinstance(limit_units, bool) or limit_units <= 0:
        raise ValueError("A meta precisa ser um número inteiro positivo de peças.")
    if not 0 <= discount_pct < 100:
        raise ValueError("O desconto deve estar entre 0 e menos de 100%.")
    required = {
        "Código", "Referência", "Descrição", "Marca", "Curva ABC",
        "Meta (dias)", "Vendas 90d filiais",
        "Estoque filiais consideradas", "Estoque M20",
        "Lead time (dias)", "Pendência considerada",
        "Embalagem", "Quantidade simulada", "Situação",
        "Saldo a comprar antes da embalagem",
    }
    missing = required - set(normal.columns)
    if missing:
        raise ValueError("Colunas ausentes no cenário normal: " + ", ".join(sorted(missing)))

    codes = normal["Código"].map(product_key).tolist()
    duplicates = {code for code in codes if code and codes.count(code) > 1}
    records = []
    for _, row in normal.iterrows():
        code = product_key(row["Código"])
        curve = str(row["Curva ABC"]).strip().upper()
        daily_sales90 = _number(row["Vendas 90d filiais"])
        stock_stores = _number(row["Estoque filiais consideradas"])
        stock_m20 = _number(row["Estoque M20"])
        confirmed = _number(row["Pendência considerada"])
        lead = _number(row["Lead time (dias"])
        pack = _number(row["Embalagem"])
        baseline = _number(row["Quantidade simulada"])
        normal_days = _number(row["Meta (dias)"])
        raw_need = _number(row["Saldo a comprar antes da embalagem"])
        normal_status = str(row["Situação"])

        valid = (
            bool(code) and code not in duplicates
            and curve in CURVE_ORDER
            and normal_status in ("SIMULAÇÃO COM COMPRA", "COBERTURA ATENDIDA")
            and all(
                v is not None and v >= 0
                for v in (daily_sales90, stock_stores, stock_m20, confirmed,
                          lead, baseline, raw_need, normal_days)
            )
            and daily_sales90 > 0
            and pack is not None and pack >= 1 and pack.is_integer()
            and baseline is not None and baseline.is_integer()
            and int(baseline) % int(pack) == 0
            and normal_days is not None and normal_days > 0
        )
        daily = daily_sales90 / 90.0 if daily_sales90 and daily_sales90 > 0 else 0.0
        present = (
            stock_stores + stock_m20
            if stock_stores is not None and stock_m20 is not None
            else None
        )
        predicted_raw = (
            present + confirmed - daily * lead
            if present is not None and confirmed is not None and lead is not None
            else None
        )
        arrival = max(0.0, predicted_raw) if predicted_raw is not None else None
        if not valid:
            reason = (
                "Código repetido" if code in duplicates else
                normal_status if normal_status not in (
                    "SIMULAÇÃO COM COMPRA", "COBERTURA ATENDIDA"
                ) else
                "Dados/embalagem inconsistentes"
            )
        else:
            reason = "Apto à distribuição"

        records.append({
            "Código": row["Código"],
            "Referência": row["Referência"],
            "Descrição": row["Descrição"],
            "Marca": row["Marca"],
            "Curva ABC": curve if curve in CURVE_ORDER else "Não identificada",
            "Consumo médio diário": daily,
            "Vendas 90d filiais": daily_sales90,
            "Estoque filiais": stock_stores,
            "Estoque M20": stock_m20,
            "Pendência confirmada": confirmed,
            "Lead time (dias)": lead,
            "Embalagem": int(pack) if pack is not None and pack >= 1 and pack.is_integer() else None,
            "Meta normal (dias)": normal_days,
            "Necessidade sem arredondamento": raw_need,
            "Necessidade normal (peças)": int(baseline) if valid else None,
            "Cobertura atual (dias)": present / daily if present is not None and daily > 0 else None,
            "Cobertura na chegada (dias)": arrival / daily if arrival is not None and daily > 0 else None,
            "Cobertura compra normal (dias)": (
                (arrival + baseline) / daily if valid else None
            ),
            "Risco de falta antes da chegada": (
                bool(predicted_raw < 0) if predicted_raw is not None and daily > 0 else None
            ),
            "_eligible": bool(valid),
            "_arrival": arrival if arrival is not None else 0.0,
            "_normal": int(baseline) if valid else 0,
            "_distributed_normal": 0,
            "_distributed_extra": 0,
            "Motivo": reason,
        })

    priority = sorted(
        [i for i, rec in enumerate(records) if rec["_eligible"]],
        key=lambda i: (
            CURVE_ORDER[records[i]["Curva ABC"]],
            records[i]["Cobertura na chegada (dias)"],
            -records[i]["Consumo médio diário"],
            product_key(records[i]["Código"]),
        ),
    )
    used = 0
    for idx in priority:
        rec = records[idx]
        package = rec["Embalagem"]
        units = min(
            rec["_normal"] // package,
            (limit_units - used) // package
        ) * package
        rec["_distributed_normal"] = units
        used += units

    normal_required = sum(rec["_normal"] for rec in records)
    normal_fully_covered = used == normal_required
    # Quando não houver espaço para atender a compra normal inteira, não
    # "engordar" itens enquanto outras necessidades permanecem descobertas.
    if normal_fully_covered and priority and used < limit_units:
        import heapq

        remainder = limit_units - used
        packages = sorted({records[i]["Embalagem"] for i in priority
                           if records[i]["Embalagem"] <= remainder})
        # A tabela de alcançabilidade procura uma combinação de embalagens que
        # atinja exatamente a meta, sem sobrecomprar uma unidade sequer.
        reachable = None
        if 0 < remainder <= 120000 and packages:
            reachable = bytearray(remainder + 1)
            reachable[0] = 1
            for package in packages:
                for units in range(package, remainder + 1):
                    if reachable[units - package]:
                        reachable[units] = 1

        for curve in ("A", "B", "C"):
            indices = [i for i in priority if records[i]["Curva ABC"] == curve]
            if not indices or remainder <= 0:
                continue
            heap = []
            for idx in indices:
                rec = records[idx]
                projected_days = (
                    rec["_arrival"] + rec["_distributed_normal"]
                ) / rec["Consumo médio diário"]
                ratio = projected_days / rec["Meta normal (dias)"]
                heapq.heappush(heap, (
                    ratio, -rec["Consumo médio diário"],
                    product_key(rec["Código"]), idx,
                ))

            while heap and remainder > 0:
                deferred = []
                chosen = None
                while heap:
                    candidate = heapq.heappop(heap)
                    idx = candidate[3]
                    package = records[idx]["Embalagem"]
                    fits = package <= remainder
                    preserves_exact = (
                        reachable is None
                        or not reachable[remainder]
                        or (fits and reachable[remainder - package])
                    )
                    if fits and preserves_exact:
                        chosen = idx
                        break
                    deferred.append(candidate)
                for entry in deferred:
                    heapq.heappush(heap, entry)
                if chosen is None:
                    break

                rec = records[chosen]
                package = rec["Embalagem"]
                rec["_distributed_extra"] += package
                used += package
                remainder -= package
                new_days = (
                    rec["_arrival"]
                    + rec["_distributed_normal"]
                    + rec["_distributed_extra"]
                ) / rec["Consumo médio diário"]
                heapq.heappush(heap, (
                    new_days / rec["Meta normal (dias)"],
                    -rec["Consumo médio diário"],
                    product_key(rec["Código"]), chosen,
                ))

    for rec in records:
        if rec["_eligible"]:
            added = rec["_distributed_normal"] + rec["_distributed_extra"]
            projected_days = (
                rec["_arrival"] + added
            ) / rec["Consumo médio diário"]
            rec["Compra proposta (peças)"] = added
            rec["Peças extras para desconto"] = rec["_distributed_extra"]
            rec["Estoque projetado após compra (peças)"] = rec["_arrival"] + added
            rec["Cobertura proposta (dias)"] = projected_days
            rec["Dias acima da meta normal"] = max(
                0.0, projected_days - rec["Meta normal (dias)"]
            )
            rec["Excesso de embalagem na compra normal (peças)"] = max(
                0.0, rec["_normal"] - rec["Necessidade sem arredondamento"]
            )
            rec["Alerta de cobertura"] = (
                "Acima de 365 dias — avaliar giro e capital"
                if projected_days > 365 else
                "Acima de 180 dias — avaliar giro"
                if projected_days > 180 else
                "Dentro de 180 dias"
            )
            rec["Resultado"] = (
                "Normal + peças adicionais para meta"
                if rec["_distributed_extra"] > 0 else
                "Compra normal parcialmente atendida"
                if rec["_distributed_normal"] < rec["_normal"] else
                "Compra normal atendida"
                if added > 0 else
                "Nenhuma compra necessária"
            )
        else:
            rec["Compra proposta (peças)"] = None
            rec["Peças extras para desconto"] = 0
            rec["Estoque projetado após compra (peças)"] = None
            rec["Cobertura proposta (dias)"] = None
            rec["Dias acima da meta normal"] = None
            rec["Excesso de embalagem na compra normal (peças)"] = None
            rec["Alerta de cobertura"] = "Conferir dados"
            rec["Resultado"] = "Fora da distribuição — conferir"

        for key in list(rec):
            if key.startswith("_"):
                del rec[key]

    table = pd.DataFrame(records)
    achieved = used == limit_units
    costs = unit_costs or {}
    cost_required = {
        product_key(row["Código"])
        for _, row in table.iterrows()
        if (_number(row["Necessidade normal (peças)"], 0) > 0
            or _number(row["Compra proposta (peças)"], 0) > 0)
    }
    missing_costs = sorted(
        code for code in cost_required
        if _number(costs.get(code)) is None or _number(costs.get(code)) <= 0
    )
    financial = None
    if cost_required and not missing_costs:
        normal_value = 0.0
        offered_value = 0.0
        for _, row in table.iterrows():
            cost = _number(costs.get(product_key(row["Código"])), 0)
            normal_value += _number(row["Necessidade normal (peças)"], 0) * cost
            offered_value += _number(row["Compra proposta (peças)"], 0) * cost
        saved = offered_value * (discount_pct / 100) if achieved else 0.0
        financial = {
            "Compra normal sem desconto (R$)": round(normal_value, 2),
            "Proposta antes do desconto (R$)": round(offered_value, 2),
            "Desconto condicional (R$)": round(saved, 2),
            "Proposta após desconto (R$)": round(offered_value - saved, 2),
            "Diferença de desembolso (R$)": round(
                offered_value - saved - normal_value, 2
            ),
        }
    return {
        "table": table,
        "normal_units": normal_required,
        "proposed_units": used,
        "extra_units": int(table["Peças extras para desconto"].sum()),
        "remaining_units": limit_units - used,
        "target_units": limit_units,
        "discount_pct": discount_pct,
        "discount_achieved": achieved,
        "normal_fully_covered": normal_fully_covered,
        "eligible_skus": len(priority),
        "blocked_skus": len(records) - len(priority),
        "proposed_skus": int(
            (pd.to_numeric(table["Compra proposta (peças)"], errors="coerce")
             .fillna(0).gt(0)).sum()
        ),
        "above_180_skus": int(
            (pd.to_numeric(table["Cobertura proposta (dias)"], errors="coerce")
             .fillna(0).gt(180)).sum()
        ),
        "above_365_skus": int(
            (pd.to_numeric(table["Cobertura proposta (dias)"], errors="coerce")
             .fillna(0).gt(365)).sum()
        ),
        "missing_cost_codes": missing_costs,
        "financial": financial,
    }

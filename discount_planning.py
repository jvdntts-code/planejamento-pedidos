"""Simulação auditável de negociação de compras por meta de peças.

Duas etapas:
1. Distribuição da necessidade normal por ABC A -> B -> C;
2. Só depois de atendida toda a necessidade normal, distribuição opcional
   até a cobertura extraordinária, novamente por A -> B -> C.

A meta é limite máximo E gatilho exato para o desconto. Não é obrigação
de comprar, e o arredondamento nunca pode ultrapassar o limite de peças.
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
    normal, expanded, limit_units=34500, discount_pct=5.0, unit_costs=None
):
    """Retorna os dois cenários e a distribuição do limite, sem tomar decisão.

    Os planos normal/expandido são produzidos por build_coverage_plan com as
    mesmas filiais, estoque, lead time e pendências; só variam dias-alvo.
    """
    if not isinstance(limit_units, int) or limit_units <= 0:
        raise ValueError("Meta de peças precisa ser um inteiro positivo.")
    if not 0 <= discount_pct < 100:
        raise ValueError("Desconto deve estar entre 0 e menos de 100%.")
    fields = {
        "Código", "Referência", "Descrição", "Marca", "Curva ABC",
        "Meta (dias)", "Vendas 90d filiais",
        "Estoque filiais consideradas", "Estoque M20",
        "Lead time (dias)", "Pendência considerada",
        "Embalagem", "Quantidade simulada", "Situação",
        "Saldo a comprar antes da embalagem",
    }
    if (fields - set(normal.columns)) or (fields - set(expanded.columns)):
        raise ValueError("Planos de cobertura incompletos para comparar a negociação.")
    if len(normal) != len(expanded):
        raise ValueError("Os dois cenários devem conter os mesmos produtos.")
    code_normal = normal["Código"].map(product_key).tolist()
    code_expanded = expanded["Código"].map(product_key).tolist()
    if code_normal != code_expanded:
        raise ValueError("Os dois cenários não possuem os mesmos códigos na mesma ordem.")

    repeated = {
        code for code in code_normal if code and code_normal.count(code) > 1
    }
    records = []
    for (_, regular), (_, extra) in zip(normal.iterrows(), expanded.iterrows()):
        code = product_key(regular["Código"])
        curve = str(regular["Curva ABC"]).strip().upper()
        stock_stores = _number(regular["Estoque filiais consideradas"], 0)
        stock_m20 = _number(regular["Estoque M20"], 0)
        pend = _number(regular["Pendência considerada"], 0)
        sales90 = _number(regular["Vendas 90d filiais"], 0)
        lead = _number(regular["Lead time (dias)"], 0)
        qty_base = _number(regular["Quantidade simulada"])
        qty_expanded = _number(extra["Quantidade simulada"])
        emb = _number(regular["Embalagem"])
        normal_days = _number(regular["Meta (dias"])
        expanded_days = _number(extra["Meta (dias"])
        original_need = _number(regular["Saldo a comprar antes da embalagem"])
        extended_need = _number(extra["Saldo a comprar antes da embalagem"])
        is_valid = (
            code not in repeated
            and curve in CURVE_ORDER
            and str(regular["Situação"]) in (
                "SIMULAÇÃO COM COMPRA", "COBERTURA ATENDIDA"
            )
            and str(extra["Situação"]) in (
                "SIMULAÇÃO COM COMPRA", "COBERTURA ATENDIDA"
            )
            and all(x is not None and x >= 0 for x in (
                stock_stores, stock_m20, pend, sales90, lead,
                qty_base, qty_expanded, normal_days, expanded_days,
                original_need, extended_need,
            ))
            and sales90 > 0
            and emb is not None and emb >= 1
            and emb.is_integer()
            and expanded_days >= normal_days
            and qty_expanded >= qty_base
            and math.isclose(
                _number(extra["Embalagem"], -1), emb, rel_tol=0, abs_tol=1e-8
            )
        )
        daily = sales90 / 90.0 if sales90 > 0 else 0.0
        raw_stock = stock_stores + stock_m20
        arrival_raw = raw_stock + pend - daily * lead
        arrival = max(0.0, arrival_raw)
        records.append({
            "Código": regular["Código"],
            "Referência": regular["Referência"],
            "Descrição": regular["Descrição"],
            "Marca": regular["Marca"],
            "Curva ABC": curve if curve in CURVE_ORDER else "Não identificada",
            "Consumo diário": daily,
            "Meta normal (dias)": normal_days,
            "Teto negociação (dias)": expanded_days,
            "Estoque filiais": stock_stores,
            "Estoque M20": stock_m20,
            "Pendência confirmada": pend,
            "Lead time (dias)": lead,
            "Embalagem": int(emb) if emb and emb > 0 and emb.is_integer() else None,
            "Necessidade sem arredondamento": original_need,
            "Necessidade normal (peças)": int(qty_base) if is_valid else None,
            "Limite extraordinário (peças)": int(qty_expanded) if is_valid else None,
            "Cobertura atual (dias)": raw_stock / daily if daily else None,
            "Cobertura na chegada (dias)": arrival / daily if daily else None,
            "Cobertura compra normal (dias)": (
                (arrival + qty_base) / daily if is_valid else None
            ),
            "Risco de falta antes da chegada": bool(
                daily > 0 and arrival_raw < 0
            ),
            "_arrival": arrival,
            "_excess_raw": extended_need,
            "_eligible": bool(is_valid),
            "_regular": int(qty_base) if is_valid else 0,
            "_maximum": int(qty_expanded) if is_valid else 0,
            "_allocated_normal": 0,
            "_allocated_extra": 0,
            "Motivo": (
                "Apto à simulação" if is_valid
                else (
                    "Código duplicado no planejamento" if code in repeated
                    else str(regular["Situação"])
                    if str(regular["Situação"]) not in (
                        "SIMULAÇÃO COM COMPRA", "COBERTURA ATENDIDA"
                    )
                    else "Conferir dados e embalagem do produto"
                )
            ),
        })

    priority = sorted(
        (i for i, record in enumerate(records) if record["_eligible"]),
        key=lambda i: (
            CURVE_ORDER[records[i]["Curva ABC"]],
            records[i]["Cobertura na chegada (dias)"],
            -records[i]["Consumo diário"],
            product_key(records[i]["Código"]),
        ),
    )
    used = 0
    # Etapa 1: atender a compra NORMAL, antes de qualquer extra.
    for index in priority:
        record = records[index]
        emb = record["Embalagem"]
        room = (limit_units - used) // emb
        requested = record["_regular"] // emb
        allocation = min(room, requested) * emb
        record["_allocated_normal"] = allocation
        used += allocation

    required_total = sum(record["_regular"] for record in records)
    normal_fully_covered = (
        sum(record["_allocated_normal"] for record in records) == required_total
    )

    # Etapa 2: só permitir extra se toda necessidade NORMAL foi atendida.
    if normal_fully_covered:
        for index in priority:
            record = records[index]
            emb = record["Embalagem"]
            room = (limit_units - used) // emb
            allowance = (record["_maximum"] -
                         record["_allocated_normal"]) // emb
            allocation = min(room, max(0, allowance)) * emb
            record["_allocated_extra"] = allocation
            used += allocation

    for record in records:
        total = record["_allocated_normal"] + record["_allocated_extra"]
        daily = record["Consumo diário"]
        after = (
            (record["_arrival"] + total) / daily
            if record["_eligible"] and daily > 0 else None
        )
        record["Compra proposta (peças)"] = (
            total if record["_eligible"] else None
        )
        record["Peças extras para desconto"] = record["_allocated_extra"]
        record["Cobertura proposta (dias)"] = after
        record["Dias acima da meta normal"] = (
            max(0.0, after - record["Meta normal (dias)"])
            if after is not None else None
        )
        record["Dias acima do teto extraordinário"] = (
            max(0.0, after - record["Teto negociação (dias)"])
            if after is not None else None
        )
        record["Excesso por embalagem (peças)"] = (
            max(0.0, total - record["_excess_raw"])
            if record["_eligible"] else None
        )
        if record["_eligible"]:
            if total == 0:
                record["Resultado"] = (
                    "Cobertura normal atendida" if record["_regular"] == 0
                    else "Sem espaço na meta / embalagem"
                )
            elif record["_allocated_normal"] < record["_regular"]:
                record["Resultado"] = "Compra normal parcialmente atendida"
            elif record["_allocated_extra"] > 0:
                record["Resultado"] = "Compra normal + extra para desconto"
            else:
                record["Resultado"] = "Compra normal atendida"
        else:
            record["Resultado"] = "Fora da distribuição — conferir"

    for record in records:
        for key in list(record):
            if key.startswith("_"):
                del record[key]
    table = pd.DataFrame(records)
    achieved = used == limit_units
    costs = unit_costs or {}
    cost_required = set()
    for _, row in table.iterrows():
        if (_number(row["Necessidade normal (peças)"], 0) > 0
                or _number(row["Compra proposta (peças)"], 0) > 0):
            cost_required.add(product_key(row["Código"]))
    missing_costs = sorted({
        code for code in cost_required
        if _number(costs.get(code)) is None or
           _number(costs.get(code)) <= 0
    })
    financial = None
    if cost_required and not missing_costs:
        regular_value = 0.0
        proposed_value = 0.0
        for _, row in table.iterrows():
            cost = _number(costs.get(product_key(row["Código"])), 0)
            regular_value += _number(row["Necessidade normal (peças)"], 0) * cost
            proposed_value += _number(row["Compra proposta (peças)"], 0) * cost
        reduction = proposed_value * (discount_pct / 100.0) if achieved else 0.0
        financial = {
            "Compra normal sem desconto (R$)": round(regular_value, 2),
            "Proposta antes do desconto (R$)": round(proposed_value, 2),
            "Desconto condicional (R$)": round(reduction, 2),
            "Proposta após desconto (R$)": round(proposed_value - reduction, 2),
            "Diferença de desembolso (R$)": round(
                proposed_value - reduction - regular_value, 2
            ),
        }
    return {
        "table": table,
        "normal_units": required_total,
        "proposed_units": used,
        "extra_units": sum(r["Peças extras para desconto"] for r in records),
        "remaining_units": limit_units - used,
        "target_units": limit_units,
        "discount_pct": discount_pct,
        "discount_achieved": achieved,
        "normal_fully_covered": normal_fully_covered,
        "eligible_skus": sum(1 for r in records if r["Motivo"] == "Apto à simulação"),
        "blocked_skus": sum(1 for r in records if r["Motivo"] != "Apto à simulação"),
        "proposed_skus": sum(
            1 for r in records if _number(r["Compra proposta (peças)"], 0) > 0
        ),
        "missing_cost_codes": missing_costs,
        "financial": financial,
    }

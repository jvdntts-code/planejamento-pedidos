"""Cenário de compra por dias de cobertura e Curva ABC já calculada.

A simulação não substitui o cálculo tradicional do NEXO nem toma
decisões sobre transferência entre filiais ou pedidos com entrega incerta.
"""
import math
import re

import pandas as pd


DEFAULT_DAYS = {"A": 90, "B": 60, "C": 30}


def product_key(value):
    if pd.isna(value):
        return ""
    return re.sub(r"[^A-Z0-9]+", "", re.sub(r"\.0$", "", str(value).strip().upper()))


def brand_key(value):
    return str(value or "").strip().casefold()


def make_abc_snapshot(products, brand, period_days):
    """Preserva a curva calculada por receita na Análise de Linha."""
    required = {"codigo", "curva_abc", "preco_venda", "vendas_periodo", "preco_venda_origem"}
    missing = required - set(products.columns)
    if missing:
        raise ValueError("A análise não possui: " + ", ".join(sorted(missing)))
    prices = pd.to_numeric(products["preco_venda"], errors="coerce")
    sales = pd.to_numeric(products["vendas_periodo"], errors="coerce").fillna(0)
    origins = products["preco_venda_origem"].fillna("").astype(str)
    unreliable = (
        (sales.gt(0) & (prices.isna() | prices.le(0)))
        | origins.str.contains("custo usado provisoriamente", case=False, regex=False)
        | (sales.gt(0) & origins.str.contains("sem preço", case=False, regex=False))
    )
    mapping = {}
    for code, curve in zip(products["codigo"], products["curva_abc"]):
        key = product_key(code)
        curve = str(curve).strip().upper()
        if not key or curve not in DEFAULT_DAYS:
            continue
        if key in mapping and mapping[key] != curve:
            raise ValueError(
                f"Código {key} consta em mais de uma Curva ABC. "
                "Corrija duplicidades antes de simular."
            )
        mapping[key] = curve
    if not brand_key(brand):
        raise ValueError("A marca da Análise de Linha não foi identificada.")
    return {
        "brand": str(brand).strip(),
        "period_days": int(period_days),
        "curves": mapping,
        "reliable_prices": not bool(unreliable.any()),
        "unreliable_prices": int(unreliable.sum()),
    }


def build_coverage_plan(base, needs, snapshot, day_targets, leadtime_days,
                        pend_by_code=None, include_pending=False):
    """Projeta necessidade de cada filial separadamente e abate M20 uma vez.

    Para cada filial considerada com venda90 > 0:
      necessidade = max(0, consumo_diario * (leadtime + cobertura_alvo) - estoque)
    A soma das necessidades das filiais é abatida do estoque M20 e, se
    explicitamente confirmado pelo comprador, das pendências previstas.
    O resultado é arredondado para a embalagem de compra do produto.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("Importe primeiro os relatórios na Análise de Linha para calcular a Curva ABC.")
    if not snapshot.get("reliable_prices"):
        raise ValueError(
            "A Curva ABC não é confiável: existem preços ausentes ou custos usados "
            "provisoriamente como preço de venda na Análise de Linha."
        )
    if leadtime_days < 0:
        raise ValueError("O lead time não pode ser negativo.")
    if any(curve not in day_targets or not 1 <= int(day_targets[curve]) <= 3650
           for curve in ("A", "B", "C")):
        raise ValueError("As metas A, B e C precisam ter de 1 a 3.650 dias.")
    required = {"codigo", "referencia", "descricao", "marca", "emb_compra", "estoque_M20"}
    missing = required - set(base.columns)
    if missing:
        raise ValueError("Colunas ausentes: " + ", ".join(sorted(missing)))
    needs_required = {
        "Codigo", "Considerada na Necessidade de Compra", "Estoque Atual", "Vendas 90d"
    }
    if needs_required - set(needs.columns):
        raise ValueError("Faltam vendas e estoques por filial para a simulação.")
    pend_by_code = pend_by_code or {}
    current_brand = brand_key(snapshot["brand"])
    curves = snapshot.get("curves", {})
    indexed_needs = needs.copy()
    indexed_needs["_codigo"] = indexed_needs["Codigo"].map(product_key)
    indexed_needs = indexed_needs[
        indexed_needs["Considerada na Necessidade de Compra"].eq("Sim")
    ]
    group = {code: frame for code, frame in indexed_needs.groupby("_codigo")}
    base_keys = base["codigo"].map(product_key)
    duplicate_keys = set(base_keys[base_keys.duplicated(keep=False)])
    records = []

    for _, item in base.iterrows():
        code = product_key(item["codigo"])
        original_brand = str(item["marca"]).strip()
        curve = curves.get(code) if brand_key(original_brand) == current_brand else None
        empty = group.get(code)
        selling = 0.0
        stock_in_stores = 0.0
        gross = 0.0
        invalid = False
        target = day_targets.get(curve) if curve else None
        if empty is not None:
            for _, store in empty.iterrows():
                stock = float(store["Estoque Atual"])
                sale90 = float(store["Vendas 90d"])
                if not math.isfinite(stock) or not math.isfinite(sale90) or stock < 0 or sale90 < 0:
                    invalid = True
                    continue
                stock_in_stores += stock
                selling += sale90
                if target is not None and sale90 > 0:
                    gross += max(
                        0.0,
                        sale90 / 90.0 * (float(target) + float(leadtime_days)) - stock
                    )

        m20 = float(item["estoque_M20"])
        pending = float(pend_by_code.get(code, 0))
        packing = float(item["emb_compra"])
        if (not math.isfinite(m20) or m20 < 0 or not math.isfinite(pending)
                or pending < 0 or not math.isfinite(packing) or packing <= 0):
            invalid = True

        status, amount, pending_used, net = "", None, 0.0, None
        if not code or code in duplicate_keys:
            status = "CONFERIR CÓDIGO DUPLICADO/AUSENTE"
        elif curve is None:
            status = "SEM CURVA ABC VERIFICADA"
        elif invalid:
            status = "CONFERIR ESTOQUE/VENDAS/EMBALAGEM"
        elif selling <= 0:
            status = "SEM VENDAS 90D NAS FILIAIS CONSIDERADAS"
            amount = 0
            net = 0.0
        else:
            pending_used = pending if include_pending else 0.0
            net = max(0.0, gross - m20 - pending_used)
            amount = int(math.ceil((net / packing) - 1e-10) * packing)
            status = "SIMULAÇÃO COM COMPRA" if amount > 0 else "COBERTURA ATENDIDA"

        records.append({
            "Código": item["codigo"],
            "Referência": item["referencia"],
            "Descrição": item["descricao"],
            "Marca": original_brand,
            "Curva ABC": curve or "Não identificada",
            "Meta (dias)": target,
            "Lead time (dias)": int(leadtime_days),
            "Vendas 90d filiais": selling,
            "Estoque filiais consideradas": stock_in_stores,
            "Estoque M20": m20,
            "Necessidade bruta filiais": round(gross, 3) if not invalid and curve else None,
            "Pendência considerada": pending_used,
            "Saldo a comprar antes da embalagem": round(net, 3) if net is not None else None,
            "Embalagem": packing,
            "Quantidade simulada": amount,
            "Situação": status,
        })
    return pd.DataFrame(records)

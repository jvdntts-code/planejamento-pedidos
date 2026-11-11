import pandas as pd
import streamlit as st


def evaluate_brand_stock(products):
    """Heurística transparente; não substitui análise por SKU."""
    if products.empty:
        return None
    x = products.copy()
    x["vendas_periodo"] = pd.to_numeric(x["vendas_periodo"], errors="coerce").fillna(0)
    x["estoque"] = pd.to_numeric(x["estoque"], errors="coerce").fillna(0)
    x["valor_estoque"] = pd.to_numeric(x["valor_estoque"], errors="coerce").fillna(0).clip(lower=0)
    active = x["vendas_periodo"] > 0
    if not active.any():
        return {"label": "SEM DADOS DE CONSUMO", "reason": "Nenhum produto apresenta vendas no período. Não é possível avaliar a saúde do estoque pelo giro.", "metrics": []}
    critical = x["status"].isin(["RUPTURA", "RISCO DE RUPTURA", "ALERTA"]) & active
    excess = x["status"].isin(["ALTO", "EXCESSO", "SEM VENDA - ESTOQUE PARADO"])
    priority = x["curva_abc"].isin(["A", "B"]) & active
    critical_count = int(critical.sum())
    active_count = int(active.sum())
    critical_pct = critical_count / active_count * 100
    priority_count = int(priority.sum())
    priority_critical = int((priority & critical).sum())
    priority_pct = priority_critical / priority_count * 100 if priority_count else 0
    total_value = float(x["valor_estoque"].sum())
    excess_value = float(x.loc[excess, "valor_estoque"].sum())
    excess_pct = excess_value / total_value * 100 if total_value > 0 else None
    metrics = [
        ("Itens com vendas em ruptura/risco/alerta", f"{critical_count}/{active_count} ({critical_pct:.1f}%)"),
        ("Itens A/B em ruptura/risco/alerta", f"{priority_critical}/{priority_count} ({priority_pct:.1f}%)" if priority_count else "Sem itens A/B com vendas"),
        ("Valor do estoque alto/excesso/parado", f"{excess_pct:.1f}%" if excess_pct is not None else "Sem valor de estoque"),
    ]
    # Precedência: problemas de abastecimento relevantes antes de capital imobilizado.
    # Limiares explícitos para uma indicação operacional, não uma norma universal.
    if critical_pct >= 20 or (priority_count and priority_pct >= 15):
        label = "ALERTA"
        reason = "Há proporção relevante de produtos com vendas em ruptura, risco ou alerta, especialmente nas curvas A/B."
    elif excess_pct is not None and excess_pct >= 40:
        label = "EXCESSO"
        reason = "Pelo menos 40% do valor de estoque está em produtos classificados como alto, excesso ou parados."
    elif excess_pct is None:
        label = "SEM AVALIAÇÃO FINANCEIRA"
        reason = "Não há valor de estoque disponível para concluir a avaliação de excesso financeiro."
    else:
        label = "SAUDÁVEL"
        reason = "Os indicadores agregados estão abaixo dos limites de alerta e excesso definidos para este veredito."
    return {"label": label, "reason": reason, "metrics": metrics}


def render_brand_verdict(products):
    verdict = evaluate_brand_stock(products)
    st.markdown("### Veredito gerencial da marca")
    if verdict is None:
        st.info("Sem produtos para avaliar.")
        return
    label = verdict["label"]
    if label == "SAUDÁVEL":
        st.success(f"**Situação geral: {label}**")
    elif label in ("ALERTA", "EXCESSO"):
        st.warning(f"**Situação geral: {label}**")
    else:
        st.info(f"**Situação geral: {label}**")
    st.write(verdict["reason"])
    if verdict["metrics"]:
        cols = st.columns(3)
        for col, (name, value) in zip(cols, verdict["metrics"]):
            col.metric(name, value)
    st.caption(
        "Critérios indicativos: ALERTA se ≥20% dos produtos com vendas estiverem em ruptura/risco/alerta "
        "ou ≥15% dos produtos A/B com vendas nessas situações. Caso contrário, EXCESSO se ≥40% "
        "do valor de estoque estiver em ALTO, EXCESSO ou PARADO. Se nenhum limite for atingido, "
        "SAUDÁVEL. ALERTA tem prioridade quando ambos ocorrerem. "
        "A avaliação utiliza as classificações ABC configuradas e não substitui a análise por produto."
    )

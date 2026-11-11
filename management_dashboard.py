"""Resumo gerencial baseado exclusivamente nas classificações e vendas calculadas."""
import pandas as pd


URGENT = ("RUPTURA", "RISCO DE RUPTURA")
ATTENTION = (*URGENT, "ALERTA")
HIGH_STOCK = ("ALTO", "EXCESSO")
NO_SALES = "SEM VENDA - ESTOQUE PARADO"


def build_management_snapshot(products, period_days):
    """Calcula indicadores objetivos sem emitir um veredito geral da marca."""
    if period_days <= 0:
        raise ValueError("O período de vendas deve ser positivo.")
    required = {
        "codigo", "descricao", "linha", "curva_abc", "status",
        "estoque", "vendas_periodo", "faturamento_periodo", "valor_estoque",
        "cobertura_dias",
    }
    missing = required.difference(products.columns)
    if missing:
        raise ValueError("Colunas ausentes na análise: " + ", ".join(sorted(missing)))
    df = products.copy()
    for field in ["estoque", "vendas_periodo", "faturamento_periodo", "valor_estoque", "cobertura_dias"]:
        df[field] = pd.to_numeric(df[field], errors="coerce")
    df["estoque"] = df["estoque"].fillna(0)
    df["vendas_periodo"] = df["vendas_periodo"].fillna(0)
    df["faturamento_periodo"] = df["faturamento_periodo"].fillna(0)
    df["valor_estoque"] = df["valor_estoque"].fillna(0)

    selling = df["vendas_periodo"] > 0
    priority = df["curva_abc"].isin(["A", "B"])
    urgent = df["status"].isin(URGENT)
    attention = df["status"].isin(ATTENTION)
    high = df["status"].isin(HIGH_STOCK)
    idle = df["status"].eq(NO_SALES)
    negative = df["estoque"] < 0

    daily = float(df.loc[selling, "vendas_periodo"].sum()) / period_days
    active_stock = float(df.loc[selling, "estoque"].clip(lower=0).sum())
    coverage_months = active_stock / daily / 30 if daily > 0 else None

    important = df.loc[attention, [
        "codigo", "descricao", "linha", "curva_abc", "status", "estoque",
        "cobertura_dias", "faturamento_periodo",
    ]].copy()
    priority_order = {"A": 0, "B": 1, "C": 2}
    status_order = {"RUPTURA": 0, "RISCO DE RUPTURA": 1, "ALERTA": 2}
    important["_curve"] = important["curva_abc"].map(priority_order).fillna(3)
    important["_status"] = important["status"].map(status_order).fillna(3)
    important = important.sort_values(
        ["_curve", "_status", "faturamento_periodo"],
        ascending=[True, True, False],
        kind="stable",
    ).drop(columns=["_curve", "_status"]).head(8)

    status_chart = (
        df["status"].value_counts()
        .reindex(["RUPTURA", "RISCO DE RUPTURA", "ALERTA", "OK",
                  "ALTO", "EXCESSO", NO_SALES, "SEM VENDA / SEM ESTOQUE",
                  "ESTOQUE NEGATIVO"], fill_value=0)
        .rename_axis("Situação").reset_index(name="Produtos")
    )
    status_chart = status_chart.loc[status_chart["Produtos"] > 0]
    line_ranking = (
        df.groupby("linha", dropna=False, as_index=False)["faturamento_periodo"]
        .sum().sort_values("faturamento_periodo", ascending=False).head(5)
    )
    provisional = (
        "preco_venda_origem" in df.columns
        and df["preco_venda_origem"].astype(str).str.contains("custo usado provisoriamente", case=False, na=False).any()
    )
    return {
        "items": len(df),
        "revenue": float(df["faturamento_periodo"].sum()),
        "stock_units": float(df["estoque"].sum()),
        "coverage_months": coverage_months,
        "daily_sales": daily,
        "urgency_ab": int((priority & urgent).sum()),
        "attention_ab": int((priority & attention).sum()),
        "urgency_all": int(urgent.sum()),
        "attention_all": int(attention.sum()),
        "high_count": int(high.sum()),
        "idle_count": int(idle.sum()),
        "negative_count": int(negative.sum()),
        "high_units": float(df.loc[high, "estoque"].clip(lower=0).sum()),
        "idle_units": float(df.loc[idle, "estoque"].clip(lower=0).sum()),
        "provisional_price": bool(provisional),
        "top_attention": important,
        "status_chart": status_chart,
        "line_ranking": line_ranking,
    }



def build_decision_center(products, period_days):
    """Fila de conferência a partir dos campos já importados; não sugere compras."""
    if period_days <= 0:
        raise ValueError("O período de análise deve ser positivo.")
    required = {
        "codigo", "descricao", "linha", "curva_abc", "status",
        "estoque", "vendas_periodo", "cobertura_dias", "faturamento_periodo",
    }
    missing = required - set(products.columns)
    if missing:
        raise ValueError("Colunas ausentes: " + ", ".join(sorted(missing)))
    df = products.copy()
    for field in ("estoque", "vendas_periodo", "cobertura_dias", "faturamento_periodo"):
        df[field] = pd.to_numeric(df[field], errors="coerce")
    df["estoque"] = df["estoque"].fillna(0)
    df["vendas_periodo"] = df["vendas_periodo"].fillna(0)
    df["faturamento_periodo"] = df["faturamento_periodo"].fillna(0)

    # Usar as faixas ABC e de cobertura já configuradas pelo usuário no NEXO.
    availability_mask = (
        df["vendas_periodo"].gt(0)
        & df["status"].isin(["RUPTURA", "RISCO DE RUPTURA", "ALERTA"])
    )
    review_mask = df["status"].isin([
        "ALTO", "EXCESSO", "SEM VENDA - ESTOQUE PARADO"
    ])
    codes = df["codigo"].fillna("").astype(str).str.strip()
    repeated = codes.ne("") & codes.duplicated(keep=False)
    negative = df["estoque"].lt(0)
    unpriced = (
        (pd.to_numeric(df["preco_venda"], errors="coerce").fillna(0) <= 0)
        & df["vendas_periodo"].gt(0)
        if "preco_venda" in df.columns
        else pd.Series(False, index=df.index)
    )
    provisional = (
        df["preco_venda_origem"].fillna("").astype(str)
        .str.contains("custo usado provisoriamente", case=False, regex=False)
        if "preco_venda_origem" in df.columns
        else pd.Series(False, index=df.index)
    )
    quality_mask = repeated | negative | unpriced | provisional | codes.eq("")

    risk = df.loc[availability_mask].copy()
    risk["Motivo"] = risk["status"].map({
        "RUPTURA": "Estoque zerado com vendas no período",
        "RISCO DE RUPTURA": "Cobertura abaixo da faixa de risco configurada",
        "ALERTA": "Cobertura na faixa de alerta configurada",
    })
    review = df.loc[review_mask].copy()
    review["Motivo"] = review["status"].map({
        "ALTO": "Cobertura acima da faixa OK configurada",
        "EXCESSO": "Cobertura acima do limite ALTO configurado",
        "SEM VENDA - ESTOQUE PARADO": f"Sem vendas em {period_days} dias e com estoque",
    })
    quality = df.loc[quality_mask].copy()
    reasons = []
    for idx in quality.index:
        flags = []
        if bool(negative.loc[idx]):
            flags.append("Estoque negativo")
        if bool(unpriced.loc[idx]):
            flags.append("Sem preço de venda válido")
        if bool(provisional.loc[idx]):
            flags.append("Preço de custo usado como preço de venda")
        if bool(repeated.loc[idx]):
            flags.append("Código repetido na base")
        if not codes.loc[idx]:
            flags.append("Código vazio")
        reasons.append("; ".join(flags))
    quality["Motivo"] = reasons

    rank_abc = {"A": 0, "B": 1, "C": 2}
    risk_rank = {"RUPTURA": 0, "RISCO DE RUPTURA": 1, "ALERTA": 2}
    review_rank = {
        "EXCESSO": 0, "SEM VENDA - ESTOQUE PARADO": 1, "ALTO": 2
    }
    risk["_status"] = risk["status"].map(risk_rank).fillna(3)
    risk["_abc"] = risk["curva_abc"].map(rank_abc).fillna(3)
    risk = risk.sort_values(
        ["_status", "_abc", "faturamento_periodo"],
        ascending=[True, True, False], kind="stable"
    ).drop(columns=["_status", "_abc"])
    review["_status"] = review["status"].map(review_rank).fillna(3)
    review = review.sort_values(
        ["_status", "estoque"], ascending=[True, False], kind="stable"
    ).drop(columns="_status")
    quality = quality.sort_values(
        ["estoque"], ascending=False, kind="stable"
    )
    return {
        "availability": risk,
        "review": review,
        "quality": quality,
        "availability_ab": int(
            (availability_mask & df["curva_abc"].isin(["A", "B"])).sum()
        ),
        "review_units": float(df.loc[review_mask, "estoque"].clip(lower=0).sum()),
        "period_days": period_days,
    }


def render_decision_center(products, period_days, integer):
    """Três perguntas gerenciais, com justificativas verificáveis por produto."""
    import streamlit as st

    findings = build_decision_center(products, period_days)
    st.markdown("#### Central de atenção do comprador")
    st.caption(
        "Informações extraídas da base importada, usando as faixas de cobertura e "
        "as curvas ABC configuradas. Não considera pedidos em aberto ou prazos de entrega."
    )

    a, b, c = st.columns(3)
    with a:
        with st.container(border=True):
            st.markdown("**Conferir abastecimento**")
            st.metric("Itens em ruptura, risco ou alerta", integer(len(findings["availability"])))
            st.caption(
                f"{integer(findings['availability_ab'])} pertencem às curvas A/B. "
                "Verifique estoque físico e reposições antes de comprar."
            )
    with b:
        with st.container(border=True):
            st.markdown("**Revisar novas compras**")
            st.metric("Itens com cobertura alta ou sem vendas", integer(len(findings["review"])))
            st.caption(
                f"{integer(findings['review_units'])} unidades nesses itens. "
                "A classificação não significa que a compra deva ser bloqueada."
            )
    with c:
        with st.container(border=True):
            st.markdown("**Conferir os dados**")
            st.metric("Registros com pontos a verificar", integer(len(findings["quality"])))
            st.caption(
                "Saldos negativos, códigos repetidos ou preços inexistentes/provisórios, "
                "quando identificados na base."
            )

    tab_risk, tab_review, tab_quality = st.tabs([
        "Abastecimento", "Cobertura elevada / sem vendas", "Inconsistências"
    ])
    for tab, key, no_items in (
        (tab_risk, "availability", "Nenhum item em ruptura, risco ou alerta."),
        (tab_review, "review", "Nenhum item com cobertura alta ou sem vendas."),
        (tab_quality, "quality", "Nenhuma inconsistência desse tipo foi identificada."),
    ):
        with tab:
            selected = findings[key]
            if selected.empty:
                st.caption(no_items)
                continue
            fields = [
                "codigo", "descricao", "curva_abc", "status",
                "estoque", "vendas_periodo", "cobertura_dias", "Motivo"
            ]
            shown = selected[fields].head(8).rename(columns={
                "codigo": "Código", "descricao": "Produto",
                "curva_abc": "ABC", "status": "Situação",
                "estoque": "Estoque atual",
                "vendas_periodo": f"Vendas {period_days}d",
                "cobertura_dias": "Cobertura (dias)",
            })
            st.dataframe(
                shown, hide_index=True, use_container_width=True,
                column_config={
                    "Cobertura (dias)": st.column_config.NumberColumn(format="%.1f"),
                    f"Vendas {period_days}d": st.column_config.NumberColumn(format="%.1f"),
                },
            )
            if len(selected) > 8:
                st.caption(
                    f"Mostrando 8 de {integer(len(selected))} registros. "
                    "Para consultar o restante, abra 'Explorar dados e relatórios'."
                )
            else:
                st.caption("As informações acima são conferências sugeridas, não pedidos de compra.")
    st.caption(
        "Atenção: 'sem vendas' refere-se somente ao período analisado. "
        "A Curva ABC depende da qualidade dos preços importados; cobertura é uma "
        "estimativa histórica, não uma previsão garantida."
    )



def render_management_overview(products, period_days, analysis_name, brl, integer):
    import streamlit as st

    data = build_management_snapshot(products, period_days)
    st.markdown("### Visão gerencial")
    st.caption(
        f"Base analisada: {analysis_name} · {period_days} dias de vendas · "
        f"{integer(data['items'])} produtos"
    )
    cols = st.columns(4)
    cols[0].metric("Faturamento calculado", brl(data["revenue"]))
    cols[1].metric("Estoque atual (un.)", integer(data["stock_units"]))
    cols[2].metric(
        "Cobertura geral (meses)",
        (f"{data['coverage_months']:.1f}".replace(".", ",")
         if data["coverage_months"] is not None else "Sem vendas"),
    )
    cols[3].metric("Curvas A/B em ruptura ou risco", integer(data["urgency_ab"]))
    st.caption(
        "Faturamento = quantidade vendida × preço unitário disponível. "
        "Cobertura = estoque positivo dos itens com vendas ÷ consumo diário ÷ 30; "
        "não representa o prazo de cada produto."
    )
    if data["provisional_price"]:
        st.warning(
            "Alguns produtos usam preço de custo provisório por falta de preço de venda. "
            "Os indicadores financeiros e a Curva ABC podem ficar distorcidos. "
            "Importe também o relatório Vendas Produtos."
        )
    if data["negative_count"]:
        st.warning(
            f"{integer(data['negative_count'])} produto(s) têm estoque negativo na base. "
            "Confira os saldos antes de utilizá-los para decisões de compra."
        )

    render_decision_center(products, period_days, integer)

    g1, g2 = st.columns([1.1, 1])
    with g1:
        st.markdown("#### Distribuição dos produtos")
        if not data["status_chart"].empty:
            chart = {
                "height": {"step": 26},
                "mark": {"type": "bar", "cornerRadiusEnd": 4},
                "encoding": {
                    "y": {"field": "Situação", "type": "nominal", "title": None,
                          "sort": "-x", "axis": {"labelLimit": 190}},
                    "x": {"field": "Produtos", "type": "quantitative",
                          "title": "Quantidade", "axis": {"tickMinStep": 1}},
                    "tooltip": [{"field": "Situação"}, {"field": "Produtos"}],
                },
                "view": {"stroke": None},
            }
            st.vega_lite_chart(data["status_chart"], chart, use_container_width=True)
    with g2:
        st.markdown("#### Linhas com maior faturamento")
        if data["line_ranking"].empty:
            st.caption("Sem linhas para apresentar.")
        else:
            ranking = data["line_ranking"].rename(
                columns={"linha": "Linha", "faturamento_periodo": "Faturamento"}
            ).copy()
            ranking["Faturamento"] = ranking["Faturamento"].apply(brl)
            st.dataframe(ranking, hide_index=True, use_container_width=True)
    st.caption(
        "Os destaques mostram quantidades e classificações do próprio relatório. "
        "Sem julgamento automático de que a marca é saudável ou está em excesso."
    )

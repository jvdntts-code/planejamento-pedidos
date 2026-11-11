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

    st.markdown("#### O que merece atenção")
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.markdown("**Disponibilidade**")
            st.metric("Ruptura/risco · todas as curvas", integer(data["urgency_all"]))
            st.caption(
                f"{integer(data['urgency_ab'])} desses itens são A/B. "
                f"Outros {integer(data['attention_all'] - data['urgency_all'])} "
                "produtos estão classificados como ALERTA."
            )
            st.caption("Conferir estoque físico e pedidos em aberto antes de decidir reposições.")
    with c2:
        with st.container(border=True):
            st.markdown("**Cobertura elevada**")
            st.metric("Produtos ALTO ou EXCESSO", integer(data["high_count"]))
            st.caption(f"{integer(data['high_units'])} unidades desses produtos em estoque.")
            st.caption("Revisar a necessidade de novas compras desses itens.")
    with c3:
        with st.container(border=True):
            st.markdown("**Sem movimentação de vendas**")
            st.metric(f"Sem vendas em {period_days} dias", integer(data["idle_count"]))
            st.caption(f"{integer(data['idle_units'])} unidades paradas no período.")
            st.caption("Verificar demanda, cadastro e histórico antes de reabastecer.")

    st.markdown("#### Produtos para conferir primeiro")
    if data["top_attention"].empty:
        st.success("Nenhum produto foi classificado como ruptura, risco ou alerta neste período.")
    else:
        view = data["top_attention"].rename(columns={
            "codigo": "Código", "descricao": "Descrição", "linha": "Linha",
            "curva_abc": "ABC", "status": "Situação", "estoque": "Estoque",
            "cobertura_dias": "Cobertura (dias)",
            "faturamento_periodo": "Faturamento calculado",
        })
        st.dataframe(
            view, use_container_width=True, hide_index=True,
            column_config={
                "Cobertura (dias)": st.column_config.NumberColumn(format="%.1f"),
                "Faturamento calculado": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )
        st.caption(
            "Até 8 produtos, priorizando curvas A/B, rupturas e riscos. "
            "É uma lista de conferência, não um pedido automático."
        )

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

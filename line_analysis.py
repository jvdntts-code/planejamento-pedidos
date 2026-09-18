import io
import re
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st


def norm(value):
    value = str(value).strip().lower()
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "", value)


def find_col(df, *names):
    mapping = {norm(c): c for c in df.columns}
    for name in names:
        key = norm(name)
        if key in mapping:
            return mapping[key]
    return None


def num(series, default=0):
    return pd.to_numeric(series, errors="coerce").fillna(default)


def read_file(uploaded):
    name = uploaded.name.lower()
    raw = uploaded.getvalue()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding=enc)
            except Exception:
                pass
    raise ValueError("Arquivo não reconhecido. Use XLSX, XLS ou CSV.")


def xlsx_bytes(sheets):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, data in sheets.items():
            sheet = name[:31]
            data.to_excel(writer, sheet_name=sheet, index=False)
            ws = writer.book[sheet]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                letter = col[0].column_letter
                max_len = max(len(str(cell.value or "")) for cell in col[:250])
                ws.column_dimensions[letter].width = min(max(max_len + 2, 11), 38)
    return output.getvalue()


def standardize_line_report(df):
    aliases = {
        "codigo": ("Codigo",),
        "descricao": ("Descrição", "Descricao"),
        "referencia": ("NumFabricante", "Numero Fabricante"),
        "linha_codigo": ("CodLinha", "Codigo Linha"),
        "linha_nome": ("Nome", "Nome Linha", "Linha"),
        "estoque": ("Estoque do Grupo", "Estoque Grupo"),
        "minimo": ("estoqueMinGrupo", "Estoque Min Grupo", "Minimo Grupo"),
        "vendas30": ("Vendas30diasRoni", "Vendas 30 dias"),
        "vendas60": ("Vendas60diasRoni", "Vendas 60 dias"),
        "vendas90": ("Vendas90diasRoni", "Vendas 90 dias"),
        "preco_venda": ("Preço Venda", "Preco Venda"),
    }

    resolved = {}
    missing = []
    for key, choices in aliases.items():
        col = find_col(df, *choices)
        if col is None:
            missing.append(choices[0])
        else:
            resolved[key] = col

    long_col = find_col(
        df,
        "Vendas360diasRoni",
        "Vendas365diasRoni",
        "Vendas 360 dias",
        "Vendas 365 dias",
    )
    if long_col is None:
        missing.append("Vendas360diasRoni")

    if missing:
        raise ValueError("Colunas ausentes no relatório: " + ", ".join(missing))

    long_days = 365 if "365" in norm(long_col) else 360

    out = pd.DataFrame()
    out["codigo"] = (
        df[resolved["codigo"]]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    out["descricao"] = df[resolved["descricao"]].fillna("").astype(str).str.strip()
    out["referencia"] = df[resolved["referencia"]].fillna("").astype(str).str.strip()
    out["linha_codigo"] = (
        df[resolved["linha_codigo"]]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    out["linha_nome"] = (
        df[resolved["linha_nome"]].fillna("SEM LINHA").astype(str).str.strip()
    )

    for key in ("estoque", "minimo", "vendas30", "vendas60", "vendas90", "preco_venda"):
        out[key] = num(df[resolved[key]], 0)

    out["vendas_longo"] = num(df[long_col], 0)
    out["linha"] = np.where(
        out["linha_nome"].ne(""),
        out["linha_codigo"] + " - " + out["linha_nome"],
        out["linha_codigo"],
    )
    out["valor_estoque"] = out["estoque"] * out["preco_venda"]
    out["faturamento_90"] = out["vendas90"] * out["preco_venda"]
    out["faturamento_longo"] = out["vendas_longo"] * out["preco_venda"]
    out = out[out["codigo"].ne("") & out["codigo"].ne("nan")].reset_index(drop=True)
    return out, long_days


def abc_with_ties(revenue):
    revenue = pd.to_numeric(revenue, errors="coerce").fillna(0)
    total = float(revenue.sum())
    if total <= 0:
        return (
            pd.Series(["C"] * len(revenue), index=revenue.index),
            pd.Series([1.0] * len(revenue), index=revenue.index),
        )

    totals_by_value = revenue.groupby(revenue).sum().sort_index(ascending=False)
    cumulative_by_value = (totals_by_value.cumsum() / total).to_dict()
    accumulated = revenue.map(cumulative_by_value).fillna(1.0)

    curve = np.select(
        [accumulated <= 0.80, accumulated <= 0.95],
        ["A", "B"],
        default="C",
    )
    return pd.Series(curve, index=revenue.index), accumulated


def classify_coverage(stock, sales, days, curve):
    if sales <= 0:
        if stock > 0:
            return "SEM VENDA - ESTOQUE PARADO"
        if stock < 0:
            return "ESTOQUE NEGATIVO"
        return "SEM VENDA / SEM ESTOQUE"

    coverage = stock / (sales / days)

    if curve == "A":
        if coverage < 30:
            return "PERIGOSO"
        if coverage < 90:
            return "ABAIXO DO RECOMENDADO"
        if coverage <= 180:
            return "OK"
        return "EXCESSO"

    if curve == "B":
        if coverage < 30:
            return "PERIGOSO"
        if coverage < 90:
            return "ABAIXO DO RECOMENDADO"
        if coverage <= 120:
            return "OK"
        if coverage <= 150:
            return "ALTO"
        return "EXCESSO"

    if coverage < 30:
        return "PERIGOSO"
    if coverage < 90:
        return "ABAIXO DO RECOMENDADO"
    if coverage <= 120:
        return "OK"
    return "EXCESSO"


def giro_curva_c(stock, sales, days, curve):
    if curve != "C":
        return ""

    if sales <= 0:
        if stock > 0:
            return "SEM VENDA - ESTOQUE PARADO"
        if stock < 0:
            return "ESTOQUE NEGATIVO"
        return "SEM VENDA / SEM ESTOQUE"

    coverage = stock / (sales / days)
    if coverage <= 30:
        return "BOA"
    if coverage <= 90:
        return "ATENÇÃO"
    if coverage <= 100:
        return "ALTO"
    return "EXCESSO"


def build_line_analysis(base, period_days):
    x = base.copy()

    if period_days == 90:
        x["vendas_periodo"] = x["vendas90"]
        x["faturamento_periodo"] = x["faturamento_90"]
    else:
        x["vendas_periodo"] = x["vendas_longo"]
        x["faturamento_periodo"] = x["faturamento_longo"]

    x["curva_abc"], x["participacao_acumulada"] = abc_with_ties(
        x["faturamento_periodo"]
    )

    total_fat = float(x["faturamento_periodo"].sum())
    x["participacao_faturamento"] = np.where(
        total_fat != 0,
        x["faturamento_periodo"] / total_fat,
        0,
    )
    x["media_diaria"] = x["vendas_periodo"] / float(period_days)
    x["cobertura_dias"] = np.where(
        x["media_diaria"] > 0,
        x["estoque"] / x["media_diaria"],
        np.nan,
    )

    x["status"] = [
        classify_coverage(float(stock), float(sales), period_days, curve)
        for stock, sales, curve in zip(
            x["estoque"], x["vendas_periodo"], x["curva_abc"]
        )
    ]
    x["alerta_giro_c"] = [
        giro_curva_c(float(stock), float(sales), period_days, curve)
        for stock, sales, curve in zip(
            x["estoque"], x["vendas_periodo"], x["curva_abc"]
        )
    ]

    keys = ["linha_codigo", "linha_nome", "linha"]

    summary = x.groupby(keys, as_index=False).agg(
        itens=("codigo", "count"),
        faturamento_90=("faturamento_90", "sum"),
        faturamento_longo=("faturamento_longo", "sum"),
        estoque_lojas=("estoque", "sum"),
        valor_estoque=("valor_estoque", "sum"),
    )

    high_mask = x["status"].isin(["ALTO", "EXCESSO"])
    stopped_mask = x["status"].eq("SEM VENDA - ESTOQUE PARADO")

    def merge_metric(frame, mask, source, name, operation="sum"):
        grouped = frame.loc[mask].groupby(keys)[source]
        series = grouped.count() if operation == "count" else grouped.sum()
        return series.rename(name).reset_index()

    metrics = [
        (high_mask, "codigo", "itens_alto_excesso", "count"),
        (high_mask, "estoque", "unid_alto_excesso", "sum"),
        (high_mask, "valor_estoque", "valor_alto_excesso", "sum"),
        (stopped_mask, "codigo", "itens_parados", "count"),
        (stopped_mask, "estoque", "unid_paradas", "sum"),
        (stopped_mask, "valor_estoque", "valor_parado", "sum"),
    ]
    for mask, source, name, operation in metrics:
        summary = summary.merge(
            merge_metric(x, mask, source, name, operation),
            on=keys,
            how="left",
        )

    status_columns = {
        "PERIGOSO": "perigoso",
        "ABAIXO DO RECOMENDADO": "abaixo_recomendado",
        "OK": "ok",
        "ALTO": "alto",
        "EXCESSO": "excesso",
        "SEM VENDA / SEM ESTOQUE": "sem_venda_sem_estoque",
        "ESTOQUE NEGATIVO": "estoque_negativo",
    }
    for status, column in status_columns.items():
        counts = (
            x.loc[x["status"].eq(status)]
            .groupby(keys)["codigo"]
            .count()
            .rename(column)
            .reset_index()
        )
        summary = summary.merge(counts, on=keys, how="left")

    fill_cols = [
        "itens_alto_excesso",
        "unid_alto_excesso",
        "valor_alto_excesso",
        "itens_parados",
        "unid_paradas",
        "valor_parado",
        *status_columns.values(),
    ]
    for col in fill_cols:
        if col not in summary.columns:
            summary[col] = 0
        summary[col] = summary[col].fillna(0)

    total_items = float(summary["itens"].sum())
    total_stock = float(summary["estoque_lojas"].sum())
    total_stock_value = float(summary["valor_estoque"].sum())
    total_fat90 = float(summary["faturamento_90"].sum())
    total_fat_long = float(summary["faturamento_longo"].sum())
    total_excess_value = float(summary["valor_alto_excesso"].sum())

    summary["pct_itens"] = np.where(total_items != 0, summary["itens"] / total_items, 0)
    summary["pct_fat_90"] = np.where(
        total_fat90 != 0, summary["faturamento_90"] / total_fat90, 0
    )
    summary["pct_fat_longo"] = np.where(
        total_fat_long != 0, summary["faturamento_longo"] / total_fat_long, 0
    )
    summary["pct_estoque"] = np.where(
        total_stock != 0, summary["estoque_lojas"] / total_stock, 0
    )
    summary["pct_valor_estoque"] = np.where(
        total_stock_value != 0, summary["valor_estoque"] / total_stock_value, 0
    )
    summary["pct_valor_excesso"] = np.where(
        total_excess_value != 0,
        summary["valor_alto_excesso"] / total_excess_value,
        0,
    )

    sort_col = "faturamento_90" if period_days == 90 else "faturamento_longo"
    summary = summary.sort_values(sort_col, ascending=False).reset_index(drop=True)
    return x, summary


def brl(value):
    return (
        f"R$ {value:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def integer(value):
    return f"{int(round(value)):,}".replace(",", ".")


def render_analise_linha():
    st.title("📊 Análise de Linha")
    st.caption(
        "Curva ABC, cobertura, excesso, estoque parado e representatividade "
        "por linha — direto do relatório bruto do sistema."
    )

    uploaded = st.file_uploader(
        "Importe o relatório bruto por marca",
        type=["xlsx", "xls", "csv"],
        key="linha_raw",
        help="Use o arquivo exatamente como ele sai do sistema.",
    )
    if not uploaded:
        st.info("Envie o relatório bruto para gerar a análise de linha.")
        return

    try:
        raw = read_file(uploaded)
        base, long_days = standardize_line_report(raw)
    except Exception as exc:
        st.error(str(exc))
        return

    period_label = st.radio(
        "Período principal da análise",
        ["90 dias", f"{long_days} dias"],
        horizontal=True,
        key="periodo_linha",
    )
    period_days = 90 if period_label == "90 dias" else long_days

    products, summary = build_line_analysis(base, period_days)
    revenue_col = "faturamento_90" if period_days == 90 else "faturamento_longo"

    total_revenue = float(products["faturamento_periodo"].sum())
    total_stock = float(products["estoque"].sum())
    stock_value = float(products["valor_estoque"].sum())
    high_mask = products["status"].isin(["ALTO", "EXCESSO"])
    stopped_mask = products["status"].eq("SEM VENDA - ESTOQUE PARADO")
    excess_value = float(products.loc[high_mask, "valor_estoque"].sum())
    stopped_value = float(products.loc[stopped_mask, "valor_estoque"].sum())

    st.success(
        f"Relatório reconhecido: {len(products)} produtos em "
        f"{products['linha'].nunique()} linhas."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs analisados", integer(len(products)))
    c2.metric(f"Faturamento {period_days}d", brl(total_revenue))
    c3.metric("Estoque lojas", integer(total_stock))
    c4.metric("Valor do estoque", brl(stock_value))

    c5, c6, c7 = st.columns(3)
    c5.metric("Itens alto/excesso", int(high_mask.sum()))
    c6.metric("Valor alto/excesso", brl(excess_value))
    c7.metric("Valor parado", brl(stopped_value))

    if not summary.empty:
        best_sales = summary.loc[summary[revenue_col].idxmax()]
        biggest_excess = summary.loc[summary["valor_alto_excesso"].idxmax()]
        biggest_stock = summary.loc[summary["estoque_lojas"].idxmax()]
        most_items = summary.loc[summary["itens"].idxmax()]

        st.markdown("### Destaques")
        d1, d2, d3, d4 = st.columns(4)
        sales_share = (
            float(best_sales[revenue_col]) / total_revenue * 100
            if total_revenue
            else 0
        )
        d1.metric(
            "Linha que mais vende",
            best_sales["linha"],
            f"{sales_share:.1f}% do faturamento",
        )
        d2.metric(
            "Maior excesso",
            biggest_excess["linha"],
            brl(float(biggest_excess["valor_alto_excesso"])),
        )
        d3.metric(
            "Maior estoque",
            biggest_stock["linha"],
            f"{integer(biggest_stock['estoque_lojas'])} un.",
        )
        d4.metric(
            "Mais SKUs",
            most_items["linha"],
            f"{int(most_items['itens'])} itens",
        )

    lines = summary["linha"].tolist()
    selected_line = st.selectbox(
        "Detalhar linha",
        ["Todas as linhas"] + lines,
        key="linha_detalhe",
    )

    products_filtered = products.copy()
    summary_filtered = summary.copy()
    if selected_line != "Todas as linhas":
        products_filtered = products_filtered[
            products_filtered["linha"].eq(selected_line)
        ].copy()
        summary_filtered = summary_filtered[
            summary_filtered["linha"].eq(selected_line)
        ].copy()

    tab1, tab2, tab3 = st.tabs(
        ["Visão por linha", "Excesso e parados", "Produtos"]
    )

    with tab1:
        display = summary_filtered[
            [
                "linha",
                "itens",
                "pct_itens",
                "faturamento_90",
                "pct_fat_90",
                "faturamento_longo",
                "pct_fat_longo",
                "estoque_lojas",
                "pct_estoque",
                "valor_estoque",
                "pct_valor_estoque",
                "itens_alto_excesso",
                "unid_alto_excesso",
                "valor_alto_excesso",
                "pct_valor_excesso",
                "itens_parados",
                "unid_paradas",
                "valor_parado",
                "perigoso",
                "abaixo_recomendado",
                "ok",
                "alto",
                "excesso",
                "sem_venda_sem_estoque",
                "estoque_negativo",
            ]
        ].copy()

        for col in (
            "pct_itens",
            "pct_fat_90",
            "pct_fat_longo",
            "pct_estoque",
            "pct_valor_estoque",
            "pct_valor_excesso",
        ):
            display[col] = display[col] * 100

        display.columns = [
            "Linha",
            "Itens",
            "% Itens",
            "Faturamento 90d",
            "% Fat. 90d",
            f"Faturamento {long_days}d",
            f"% Fat. {long_days}d",
            "Estoque Lojas",
            "% Estoque",
            "Valor Estoque",
            "% Valor Estoque",
            "Itens Alto/Excesso",
            "Unid. Alto/Excesso",
            "Valor Alto/Excesso",
            "% Valor Excesso",
            "Itens Parados",
            "Unid. Paradas",
            "Valor Parado",
            "Perigoso",
            "Abaixo Recomend.",
            "OK",
            "Alto",
            "Excesso",
            "Sem Venda/Sem Estoque",
            "Estoque Negativo",
        ]

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "% Itens": st.column_config.NumberColumn(format="%.1f%%"),
                "% Fat. 90d": st.column_config.NumberColumn(format="%.1f%%"),
                f"% Fat. {long_days}d": st.column_config.NumberColumn(format="%.1f%%"),
                "% Estoque": st.column_config.NumberColumn(format="%.1f%%"),
                "% Valor Estoque": st.column_config.NumberColumn(format="%.1f%%"),
                "% Valor Excesso": st.column_config.NumberColumn(format="%.1f%%"),
                "Faturamento 90d": st.column_config.NumberColumn(format="R$ %.2f"),
                f"Faturamento {long_days}d": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Alto/Excesso": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Parado": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

        if selected_line == "Todas as linhas" and len(summary) > 1:
            chart_data = summary.set_index("linha")[[revenue_col]].rename(
                columns={revenue_col: f"Faturamento {period_days}d"}
            )
            st.markdown("#### Faturamento por linha")
            st.bar_chart(chart_data, use_container_width=True)

    with tab2:
        kind = st.radio(
            "Mostrar",
            ["Alto / Excesso", "Estoque parado"],
            horizontal=True,
            key="tipo_alerta_linha",
        )
        if kind == "Alto / Excesso":
            alert = products_filtered[
                products_filtered["status"].isin(["ALTO", "EXCESSO"])
            ].copy()
        else:
            alert = products_filtered[
                products_filtered["status"].eq("SEM VENDA - ESTOQUE PARADO")
            ].copy()

        alert_show = alert[
            [
                "codigo",
                "referencia",
                "descricao",
                "linha",
                "estoque",
                "minimo",
                "vendas90",
                "vendas_longo",
                "preco_venda",
                "curva_abc",
                "cobertura_dias",
                "status",
                "valor_estoque",
            ]
        ].copy()
        alert_show.columns = [
            "Código",
            "Referência",
            "Descrição",
            "Linha",
            "Estoque",
            "Mínimo",
            "Vendas 90d",
            f"Vendas {long_days}d",
            "Preço Venda",
            "Curva ABC",
            "Cobertura (dias)",
            "Status",
            "Valor Estoque",
        ]
        st.dataframe(
            alert_show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Preço Venda": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
                "Cobertura (dias)": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    with tab3:
        f1, f2 = st.columns(2)
        curves = f1.multiselect(
            "Curva ABC",
            ["A", "B", "C"],
            default=["A", "B", "C"],
            key="filtro_curva_linha",
        )
        status_options = sorted(products_filtered["status"].dropna().unique().tolist())
        selected_status = f2.multiselect(
            "Status",
            status_options,
            default=status_options,
            key="filtro_status_linha",
        )

        detail = products_filtered[
            products_filtered["curva_abc"].isin(curves)
            & products_filtered["status"].isin(selected_status)
        ].copy()

        detail["participacao_acumulada"] = detail["participacao_acumulada"] * 100

        detail_show = detail[
            [
                "codigo",
                "referencia",
                "descricao",
                "linha",
                "estoque",
                "minimo",
                "vendas30",
                "vendas60",
                "vendas90",
                "vendas_longo",
                "preco_venda",
                "faturamento_periodo",
                "curva_abc",
                "participacao_acumulada",
                "cobertura_dias",
                "status",
                "alerta_giro_c",
                "valor_estoque",
            ]
        ].copy()
        detail_show.columns = [
            "Código",
            "Referência",
            "Descrição",
            "Linha",
            "Estoque",
            "Mínimo",
            "Vendas 30d",
            "Vendas 60d",
            "Vendas 90d",
            f"Vendas {long_days}d",
            "Preço Venda",
            f"Faturamento {period_days}d",
            "Curva ABC",
            "Participação Acumulada",
            "Cobertura (dias)",
            "Status",
            "Giro Curva C",
            "Valor Estoque",
        ]
        st.dataframe(
            detail_show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Preço Venda": st.column_config.NumberColumn(format="R$ %.2f"),
                f"Faturamento {period_days}d": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
                "Participação Acumulada": st.column_config.NumberColumn(format="%.1f%%"),
                "Cobertura (dias)": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    export = xlsx_bytes(
        {
            "Resumo por Linha": summary,
            "Produtos Analisados": products,
            "Alto e Excesso": products[
                products["status"].isin(["ALTO", "EXCESSO"])
            ].copy(),
            "Estoque Parado": products[
                products["status"].eq("SEM VENDA - ESTOQUE PARADO")
            ].copy(),
            "Relatorio Bruto": raw,
        }
    )
    st.download_button(
        "⬇️ Exportar análise de linha (.xlsx)",
        data=export,
        file_name=f"analise_linha_{period_days}d.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        key="download_analise_linha",
    )

    with st.expander("Critérios utilizados"):
        st.markdown(
            "**Curva ABC:** A até 80% do faturamento acumulado; B de 80% a 95%; "
            "C acima de 95%.\n\n"
            "**Curva A:** <30 dias Perigoso; 30–<90 Abaixo; 90–180 OK; >180 Excesso.\n\n"
            "**Curva B:** <30 Perigoso; 30–<90 Abaixo; 90–120 OK; >120–150 Alto; >150 Excesso.\n\n"
            "**Curva C:** <30 Perigoso; 30–<90 Abaixo; 90–120 OK; >120 Excesso.\n\n"
            "Itens sem venda e com saldo positivo são classificados como "
            "**Estoque parado**."
        )

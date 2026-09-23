import base64
import io
import json
import re
import textwrap
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from openpyxl.drawing.image import Image as XLImage
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


NAVY = "17365D"
BLUE = "2F75B5"
LIGHT_BLUE = "D9EAF7"
GREEN = "70AD47"
LIGHT_GREEN = "E2F0D9"
YELLOW = "FFD966"
LIGHT_YELLOW = "FFF2CC"
ORANGE = "ED7D31"
LIGHT_ORANGE = "FCE4D6"
RED = "C00000"
LIGHT_RED = "F4CCCC"
GRAY = "7F8C8D"
LIGHT_GRAY = "F2F2F2"
DARK = "1F1F1F"
WHITE = "FFFFFF"

LINE_CHART_COLORS = [
    "#2563EB",  # azul
    "#0F766E",  # verde petróleo
    "#7C3AED",  # roxo
    "#D97706",  # âmbar
    "#0891B2",  # ciano
    "#64748B",  # cinza azulado
    "#DB2777",  # magenta
    "#65A30D",  # verde oliva
]

STATUS_COLOR_DOMAIN = [
    "RUPTURA",
    "RISCO DE RUPTURA",
    "OK",
    "ALTO",
    "EXCESSO",
    "SEM VENDA - ESTOQUE PARADO",
    "SEM VENDA / SEM ESTOQUE",
    "ESTOQUE NEGATIVO",
]
STATUS_COLOR_RANGE = [
    "#DC2626",
    "#F97316",
    "#16A34A",
    "#EAB308",
    "#7C3AED",
    "#64748B",
    "#94A3B8",
    "#991B1B",
]

ABC_COLOR_DOMAIN = ["A", "B", "C"]
ABC_COLOR_RANGE = ["#16A34A", "#2563EB", "#94A3B8"]

PERSISTENT_CRITERIA_FILE = "saved_line_criteria.json"
DEFAULT_GITHUB_REPO = "jvdntts-code/planejamento-pedidos"
DEFAULT_GITHUB_BRANCH = "main"

DEFAULT_CRITERIA = {
    "abc_period": 90,
    "abc_a": 80.0,
    "abc_b": 95.0,
    "A_ruptura": 30,
    "A_abaixo": 90,
    "A_ok": 180,
    "A_alto": 240,
    "B_ruptura": 30,
    "B_abaixo": 90,
    "B_ok": 120,
    "B_alto": 150,
    "C_ruptura": 30,
    "C_abaixo": 90,
    "C_ok": 120,
    "C_alto": 150,
}


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


def line_import_template_bytes():
    colunas = [
        "Codigo",
        "Descrição",
        "NumFabricante",
        "CodLinha",
        "Nome",
        "Estoque do Grupo",
        "estoqueMinGrupo",
        "Vendas30diasRoni",
        "Vendas60diasRoni",
        "Vendas90diasRoni",
        "Vendas360diasRoni",
        "Preço Venda",
    ]

    modelo = pd.DataFrame(columns=colunas)

    instrucoes = pd.DataFrame([
        {
            "Etapa": 1,
            "Orientação": "Use a aba MODELO IMPORTACAO como base e mantenha os nomes dos cabeçalhos."
        },
        {
            "Etapa": 2,
            "Orientação": "Preencha uma linha por produto. Não inclua totais, subtotais ou títulos no meio da tabela."
        },
        {
            "Etapa": 3,
            "Orientação": "Codigo é o código interno do produto; NumFabricante é a referência do fabricante."
        },
        {
            "Etapa": 4,
            "Orientação": "CodLinha e Nome identificam a linha/grupo do produto e são usados nos resumos gerenciais."
        },
        {
            "Etapa": 5,
            "Orientação": "Estoque, mínimo, vendas e preço devem ser informados como valores numéricos."
        },
        {
            "Etapa": 6,
            "Orientação": "As vendas de 30, 60 e 90 dias são acumuladas e usadas para estimar períodos intermediários."
        },
        {
            "Etapa": 7,
            "Orientação": "A coluna longa pode ser Vendas360diasRoni ou Vendas365diasRoni. Este modelo usa 360 dias."
        },
        {
            "Etapa": 8,
            "Orientação": "Preço Venda é usado para calcular faturamento estimado e valor do estoque."
        },
        {
            "Etapa": 9,
            "Orientação": "Salve preferencialmente em .xlsx. O NEXO também aceita .xls e .csv."
        },
        {
            "Etapa": 10,
            "Orientação": "Antes de importar, confira se nenhum cabeçalho obrigatório foi removido ou alterado."
        },
    ])

    dicionario = pd.DataFrame([
        {"Campo": "Codigo", "Descrição": "Código interno do produto", "Tipo esperado": "Texto / número", "Obrigatório": "Sim"},
        {"Campo": "Descrição", "Descrição": "Descrição do produto", "Tipo esperado": "Texto", "Obrigatório": "Sim"},
        {"Campo": "NumFabricante", "Descrição": "Referência ou número do fabricante", "Tipo esperado": "Texto", "Obrigatório": "Sim"},
        {"Campo": "CodLinha", "Descrição": "Código da linha do produto", "Tipo esperado": "Texto / número", "Obrigatório": "Sim"},
        {"Campo": "Nome", "Descrição": "Nome da linha do produto", "Tipo esperado": "Texto", "Obrigatório": "Sim"},
        {"Campo": "Estoque do Grupo", "Descrição": "Estoque atual consolidado do grupo", "Tipo esperado": "Número", "Obrigatório": "Sim"},
        {"Campo": "estoqueMinGrupo", "Descrição": "Estoque mínimo consolidado do grupo", "Tipo esperado": "Número", "Obrigatório": "Sim"},
        {"Campo": "Vendas30diasRoni", "Descrição": "Vendas acumuladas dos últimos 30 dias", "Tipo esperado": "Número", "Obrigatório": "Sim"},
        {"Campo": "Vendas60diasRoni", "Descrição": "Vendas acumuladas dos últimos 60 dias", "Tipo esperado": "Número", "Obrigatório": "Sim"},
        {"Campo": "Vendas90diasRoni", "Descrição": "Vendas acumuladas dos últimos 90 dias", "Tipo esperado": "Número", "Obrigatório": "Sim"},
        {"Campo": "Vendas360diasRoni", "Descrição": "Vendas acumuladas dos últimos 360 dias; 365 dias também é aceito", "Tipo esperado": "Número", "Obrigatório": "Sim"},
        {"Campo": "Preço Venda", "Descrição": "Preço unitário de venda usado nas análises financeiras", "Tipo esperado": "Número", "Obrigatório": "Sim"},
    ])

    exemplo = pd.DataFrame([{
        "Codigo": "10001",
        "Descrição": "PRODUTO EXEMPLO",
        "NumFabricante": "REF-001",
        "CodLinha": "10",
        "Nome": "LINHA EXEMPLO",
        "Estoque do Grupo": 50,
        "estoqueMinGrupo": 20,
        "Vendas30diasRoni": 15,
        "Vendas60diasRoni": 32,
        "Vendas90diasRoni": 48,
        "Vendas360diasRoni": 190,
        "Preço Venda": 99.90,
    }])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        modelo.to_excel(writer, sheet_name="MODELO IMPORTACAO", index=False)
        instrucoes.to_excel(writer, sheet_name="INSTRUCOES", index=False)
        dicionario.to_excel(writer, sheet_name="DICIONARIO", index=False)
        exemplo.to_excel(writer, sheet_name="EXEMPLO", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            ws.sheet_view.showGridLines = False

            for cell in ws[1]:
                cell.font = Font(name="Times New Roman", bold=True, color=WHITE)
                cell.fill = PatternFill("solid", fgColor=NAVY)
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.font = Font(name="Times New Roman", size=11)
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

            for col in ws.columns:
                letter = get_column_letter(col[0].column)
                values = [str(cell.value or "") for cell in col[:200]]
                width = max([len(v) for v in values] + [10]) + 2
                ws.column_dimensions[letter].width = min(max(width, 12), 48)

            ws.row_dimensions[1].height = 30

    output.seek(0)
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


def sales_for_period(df, days, long_days):
    """Estima vendas acumuladas para qualquer período usando os pontos 30/60/90/longo."""
    days = max(int(days), 1)

    v30 = pd.to_numeric(df["vendas30"], errors="coerce").fillna(0).astype(float)
    v60 = pd.to_numeric(df["vendas60"], errors="coerce").fillna(0).astype(float)
    v90 = pd.to_numeric(df["vendas90"], errors="coerce").fillna(0).astype(float)
    vlong = pd.to_numeric(df["vendas_longo"], errors="coerce").fillna(0).astype(float)

    if days <= 30:
        result = v30 * (days / 30.0)
    elif days <= 60:
        result = v30 + (v60 - v30) * ((days - 30) / 30.0)
    elif days <= 90:
        result = v60 + (v90 - v60) * ((days - 60) / 30.0)
    elif days <= long_days:
        span = max(long_days - 90, 1)
        result = v90 + (vlong - v90) * ((days - 90) / float(span))
    else:
        result = vlong * (days / float(max(long_days, 1)))

    return result.clip(lower=0)


def abc_with_ties(revenue, cut_a=80.0, cut_b=95.0):
    revenue = pd.to_numeric(revenue, errors="coerce").fillna(0)
    total = float(revenue.sum())
    if total <= 0:
        return (
            pd.Series(["C"] * len(revenue), index=revenue.index),
            pd.Series([1.0] * len(revenue), index=revenue.index),
        )

    cut_a = float(cut_a) / 100.0
    cut_b = float(cut_b) / 100.0
    totals_by_value = revenue.groupby(revenue).sum().sort_index(ascending=False)
    cumulative_by_value = (totals_by_value.cumsum() / total).to_dict()
    accumulated = revenue.map(cumulative_by_value).fillna(1.0)
    curve = np.select(
        [accumulated <= cut_a, accumulated <= cut_b],
        ["A", "B"],
        default="C",
    )
    return pd.Series(curve, index=revenue.index), accumulated


def classify_coverage(stock, sales, days, curve, criteria):
    if stock < 0:
        return "ESTOQUE NEGATIVO"
    if sales <= 0:
        return "SEM VENDA - ESTOQUE PARADO" if stock > 0 else "SEM VENDA / SEM ESTOQUE"

    coverage = stock / (sales / days)
    ruptura = float(criteria[f"{curve}_ruptura"])
    abaixo = float(criteria[f"{curve}_abaixo"])
    ok_max = float(criteria[f"{curve}_ok"])

    alto_max = float(criteria[f"{curve}_alto"])

    if coverage < ruptura:
        return "RUPTURA"
    if coverage < abaixo:
        return "RISCO DE RUPTURA"
    if coverage <= ok_max:
        return "OK"
    if coverage <= alto_max:
        return "ALTO"
    return "EXCESSO"


def giro_curva_c(stock, sales, days, curve):
    if curve != "C":
        return ""
    if stock < 0:
        return "ESTOQUE NEGATIVO"
    if sales <= 0:
        return "SEM VENDA - ESTOQUE PARADO" if stock > 0 else "SEM VENDA / SEM ESTOQUE"

    coverage = stock / (sales / days)
    if coverage <= 30:
        return "BOA"
    if coverage <= 90:
        return "ATENÇÃO"
    if coverage <= 100:
        return "ALTO"
    return "EXCESSO"


def build_line_analysis(base, period_days, criteria, long_days):
    x = base.copy()

    x["vendas_periodo"] = sales_for_period(x, period_days, long_days)
    x["faturamento_periodo"] = x["vendas_periodo"] * x["preco_venda"]

    x["curva_abc"], x["participacao_acumulada"] = abc_with_ties(
        x["faturamento_periodo"],
        criteria["abc_a"],
        criteria["abc_b"],
    )

    total_abc = float(x["faturamento_periodo"].sum())
    x["participacao_faturamento"] = np.where(
        total_abc != 0,
        x["faturamento_periodo"] / total_abc,
        0,
    )
    x["media_diaria"] = x["vendas_periodo"] / float(period_days)
    x["cobertura_dias"] = np.where(
        x["media_diaria"] > 0,
        x["estoque"] / x["media_diaria"],
        np.nan,
    )
    x["status"] = [
        classify_coverage(float(stock), float(sales), period_days, curve, criteria)
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
        faturamento_analise=("faturamento_periodo", "sum"),
        faturamento_90=("faturamento_90", "sum"),
        faturamento_longo=("faturamento_longo", "sum"),
        estoque_lojas=("estoque", "sum"),
        valor_estoque=("valor_estoque", "sum"),
    )

    high_mask = x["status"].isin(["ALTO", "EXCESSO"])
    stopped_mask = x["status"].eq("SEM VENDA - ESTOQUE PARADO")

    def grouped(mask, source, name, op="sum"):
        group = x.loc[mask].groupby(keys)[source]
        series = group.count() if op == "count" else group.sum()
        return series.rename(name).reset_index()

    metrics = [
        (high_mask, "codigo", "itens_alto_excesso", "count"),
        (high_mask, "estoque", "unid_alto_excesso", "sum"),
        (high_mask, "valor_estoque", "valor_alto_excesso", "sum"),
        (stopped_mask, "codigo", "itens_parados", "count"),
        (stopped_mask, "estoque", "unid_paradas", "sum"),
        (stopped_mask, "valor_estoque", "valor_parado", "sum"),
    ]
    for mask, source, name, op in metrics:
        summary = summary.merge(grouped(mask, source, name, op), on=keys, how="left")

    status_columns = {
        "RUPTURA": "ruptura",
        "RISCO DE RUPTURA": "risco_ruptura",
        "OK": "ok",
        "ALTO": "alto",
        "EXCESSO": "excesso",
        "SEM VENDA - ESTOQUE PARADO": "estoque_parado",
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

    summary = summary.sort_values("faturamento_analise", ascending=False).reset_index(drop=True)
    return x, summary


def brl(value):
    return (
        f"R$ {float(value):,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def integer(value):
    return f"{int(round(float(value))):,}".replace(",", ".")


def _pie_chart(
    data,
    category,
    value,
    title,
    description,
    value_label="Valor",
    color_domain=None,
    color_range=None,
):
    chart_data = data[[category, value]].copy()
    chart_data[value] = pd.to_numeric(chart_data[value], errors="coerce").fillna(0)
    chart_data = chart_data[chart_data[value] > 0].copy()

    total = float(chart_data[value].sum())
    if chart_data.empty or total <= 0:
        st.info("Sem dados para este gráfico.")
        return

    chart_data["percentual"] = chart_data[value] / total
    chart_data["participacao"] = (chart_data["percentual"] * 100).round(1)

    color_encoding = {
        "field": category,
        "type": "nominal",
        "legend": {
            "title": None,
            "orient": "bottom",
            "columns": 2,
            "labelLimit": 260,
        },
    }
    if color_domain and color_range:
        color_encoding["scale"] = {
            "domain": color_domain,
            "range": color_range,
        }

    spec = {
        "mark": {
            "type": "arc",
            "outerRadius": 118,
            "stroke": "#111827",
            "strokeWidth": 1,
        },
        "encoding": {
            "theta": {
                "field": value,
                "type": "quantitative",
                "stack": True,
            },
            "color": color_encoding,
            "tooltip": [
                {"field": category, "type": "nominal", "title": category},
                {"field": value, "type": "quantitative", "title": value_label, "format": ",.2f"},
                {"field": "participacao", "type": "quantitative", "title": "Participação (%)", "format": ".1f"},
            ],
        },
        "view": {"stroke": None},
    }

    st.markdown(f"**{title}**")
    st.caption(description)
    st.vega_lite_chart(
        chart_data,
        spec,
        use_container_width=True,
    )


def _card_html(title, value, subtitle=""):
    return f"""
    <div style="
        border:1px solid rgba(128,128,128,.25);
        border-radius:14px;
        padding:16px 18px;
        min-height:112px;
        background:rgba(128,128,128,.05);
    ">
        <div style="font-size:13px;opacity:.72;margin-bottom:8px">{title}</div>
        <div style="font-size:27px;font-weight:700;line-height:1.1">{value}</div>
        <div style="font-size:12px;opacity:.66;margin-top:8px">{subtitle}</div>
    </div>
    """


def _friendly_summary(summary, long_days):
    df = summary[
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
            "valor_alto_excesso",
            "valor_parado",
            "ruptura",
            "risco_ruptura",
            "ok",
            "alto",
            "excesso",
            "estoque_parado",
        ]
    ].copy()
    df.columns = [
        "Linha",
        "SKUs",
        "% SKUs",
        "Faturamento 90d",
        "% Fat. 90d",
        f"Faturamento {long_days}d",
        f"% Fat. {long_days}d",
        "Estoque (un.)",
        "% Estoque",
        "Valor Estoque",
        "Valor Alto/Excesso",
        "Valor Parado",
        "Ruptura",
        "Risco Ruptura",
        "OK",
        "Alto",
        "Excesso",
        "Parados",
    ]
    return df


def _friendly_products(products, long_days, period_days):
    df = products[
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
    df.columns = [
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
    return df


def _style_header(ws, row):
    for cell in ws[row]:
        if cell.value is None:
            continue
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(color=WHITE, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30


def _auto_width(ws, min_width=10, max_width=34):
    for col_idx in range(1, ws.max_column + 1):
        letter = get_column_letter(col_idx)
        longest = 0
        for row_idx in range(1, min(ws.max_row, 300) + 1):
            value = ws.cell(row_idx, col_idx).value
            if value is not None:
                longest = max(longest, len(str(value)))
        ws.column_dimensions[letter].width = min(max(longest + 2, min_width), max_width)


def _add_excel_table(ws, start_row, name):
    if ws.max_row <= start_row:
        return
    ref = f"A{start_row}:{get_column_letter(ws.max_column)}{ws.max_row}"
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)


def _format_sheet(
    ws,
    header_row=1,
    table_name=None,
    currency_headers=None,
    percent_headers=None,
    decimal_headers=None,
    status_header=None,
    curve_header=None,
):
    currency_headers = set(currency_headers or [])
    percent_headers = set(percent_headers or [])
    decimal_headers = set(decimal_headers or [])

    ws.sheet_view.showGridLines = False
    ws.freeze_panes = f"A{header_row + 1}"
    _style_header(ws, header_row)

    headers = {
        str(ws.cell(header_row, c).value): c
        for c in range(1, ws.max_column + 1)
        if ws.cell(header_row, c).value is not None
    }

    thin = Side(style="thin", color="D9E1F2")
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
        for cell in row:
            cell.border = Border(bottom=thin)
            cell.alignment = Alignment(vertical="center")

    for header in currency_headers:
        if header in headers:
            col = headers[header]
            for r in range(header_row + 1, ws.max_row + 1):
                ws.cell(r, col).number_format = 'R$ #,##0.00'

    for header in percent_headers:
        if header in headers:
            col = headers[header]
            for r in range(header_row + 1, ws.max_row + 1):
                ws.cell(r, col).number_format = '0.0%'

    for header in decimal_headers:
        if header in headers:
            col = headers[header]
            for r in range(header_row + 1, ws.max_row + 1):
                ws.cell(r, col).number_format = '0.0'

    status_fills = {
        "RUPTURA": PatternFill("solid", fgColor=LIGHT_RED),
        "RISCO DE RUPTURA": PatternFill("solid", fgColor=LIGHT_YELLOW),
        "OK": PatternFill("solid", fgColor=LIGHT_GREEN),
        "ALTO": PatternFill("solid", fgColor=LIGHT_ORANGE),
        "EXCESSO": PatternFill("solid", fgColor="F8CBAD"),
        "SEM VENDA - ESTOQUE PARADO": PatternFill("solid", fgColor="D9D9D9"),
        "SEM VENDA / SEM ESTOQUE": PatternFill("solid", fgColor="EDEDED"),
        "ESTOQUE NEGATIVO": PatternFill("solid", fgColor="F4B183"),
    }
    if status_header and status_header in headers:
        col = headers[status_header]
        for r in range(header_row + 1, ws.max_row + 1):
            cell = ws.cell(r, col)
            if cell.value in status_fills:
                cell.fill = status_fills[cell.value]
                cell.font = Font(bold=True)

    curve_fills = {
        "A": PatternFill("solid", fgColor="C6E0B4"),
        "B": PatternFill("solid", fgColor="FFE699"),
        "C": PatternFill("solid", fgColor="F4B183"),
    }
    if curve_header and curve_header in headers:
        col = headers[curve_header]
        for r in range(header_row + 1, ws.max_row + 1):
            cell = ws.cell(r, col)
            if cell.value in curve_fills:
                cell.fill = curve_fills[cell.value]
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center")

    _auto_width(ws)

    # Mantemos o AutoFiltro normal da planilha, sem criar objetos "Tabela"
    # (xl/tables/table*.xml). Em algumas versões do Excel, a combinação de
    # tabelas geradas pelo openpyxl com este layout estilizado fazia o Excel
    # reparar/remover os Table XMLs ao abrir o arquivo.
    if ws.max_row > header_row and ws.max_column > 0:
        ws.auto_filter.ref = (
            f"A{header_row}:{get_column_letter(ws.max_column)}{ws.max_row}"
        )
    else:
        ws.auto_filter.ref = None


def _write_card(ws, col_start, col_end, row_start, title, value, fill_color):
    ws.merge_cells(
        start_row=row_start,
        start_column=col_start,
        end_row=row_start,
        end_column=col_end,
    )
    ws.merge_cells(
        start_row=row_start + 1,
        start_column=col_start,
        end_row=row_start + 2,
        end_column=col_end,
    )
    title_cell = ws.cell(row_start, col_start)
    value_cell = ws.cell(row_start + 1, col_start)
    title_cell.value = title
    value_cell.value = value

    for r in range(row_start, row_start + 3):
        for c in range(col_start, col_end + 1):
            ws.cell(r, c).fill = PatternFill("solid", fgColor=fill_color)
            ws.cell(r, c).border = Border(
                left=Side(style="thin", color="D9E1F2"),
                right=Side(style="thin", color="D9E1F2"),
                top=Side(style="thin", color="D9E1F2"),
                bottom=Side(style="thin", color="D9E1F2"),
            )

    title_cell.font = Font(bold=True, color=DARK, size=10)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    value_cell.font = Font(bold=True, color=DARK, size=18)
    value_cell.alignment = Alignment(horizontal="center", vertical="center")


def _excel_pie_image(
    labels,
    values,
    title,
    description,
    colors=None,
):
    labels = [str(x) for x in labels]
    values = [float(x) for x in values]

    filtered = [
        (label, value, i)
        for i, (label, value) in enumerate(zip(labels, values))
        if value > 0
    ]
    if not filtered:
        filtered = [("Sem dados", 1.0, 0)]

    labels = [x[0] for x in filtered]
    values = [x[1] for x in filtered]
    idxs = [x[2] for x in filtered]

    if colors:
        palette = [colors[i % len(colors)] for i in idxs]
    else:
        palette = LINE_CHART_COLORS[: len(values)]
        if len(palette) < len(values):
            palette = [
                LINE_CHART_COLORS[i % len(LINE_CHART_COLORS)]
                for i in range(len(values))
            ]

    fig, ax = plt.subplots(figsize=(7.2, 4.7), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    def autopct(pct):
        return f"{pct:.1f}%" if pct >= 3 else ""

    wedges, _, autotexts = ax.pie(
        values,
        startangle=90,
        counterclock=False,
        colors=palette,
        autopct=autopct,
        pctdistance=0.72,
        wedgeprops={"edgecolor": "white", "linewidth": 1.2},
    )

    for txt in autotexts:
        txt.set_fontsize(8)
        txt.set_color("#111827")
        txt.set_weight("bold")

    ax.axis("equal")
    ax.legend(
        wedges,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=2,
        frameon=False,
        fontsize=7,
        handlelength=1.0,
        columnspacing=1.2,
    )

    fig.suptitle(
        title,
        fontsize=13,
        fontweight="bold",
        color="#17365D",
        y=0.98,
    )
    fig.text(
        0.5,
        0.91,
        textwrap.fill(description, width=78),
        ha="center",
        va="top",
        fontsize=8.2,
        color="#475569",
    )
    fig.subplots_adjust(top=0.82, bottom=0.25, left=0.06, right=0.94)

    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)
    buffer.seek(0)
    return buffer



def _excel_abc_compare_image(products, period_days):
    abc = (
        products.groupby("curva_abc", dropna=False)
        .agg(
            faturamento=("faturamento_periodo", "sum"),
            valor_estoque=("valor_estoque", "sum"),
        )
        .reindex(["A", "B", "C"], fill_value=0)
    )

    sales_total = float(abc["faturamento"].sum())
    stock_total = float(abc["valor_estoque"].sum())
    sales_pct = (
        abc["faturamento"] / sales_total * 100
        if sales_total
        else abc["faturamento"] * 0
    )
    stock_pct = (
        abc["valor_estoque"] / stock_total * 100
        if stock_total
        else abc["valor_estoque"] * 0
    )

    labels = ["A", "B", "C"]
    x = np.arange(len(labels))
    width = 0.34

    fig, ax = plt.subplots(figsize=(7.2, 4.7), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bars_sales = ax.bar(x - width / 2, sales_pct.values, width, label="% Vendas")
    bars_stock = ax.bar(x + width / 2, stock_pct.values, width, label="% Valor Estoque")

    ax.set_ylim(0, 100)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Participação (%)")
    ax.grid(axis="y", alpha=0.18)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for bars in (bars_sales, bars_stock):
        for bar in bars:
            height = float(bar.get_height())
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + 1.2,
                f"{height:.1f}%",
                ha="center",
                va="bottom",
                fontsize=8,
                fontweight="bold",
            )

    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=2,
        frameon=False,
        fontsize=8,
    )

    fig.suptitle(
        "Curva ABC — vendas x valor do estoque",
        fontsize=13,
        fontweight="bold",
        color="#17365D",
        y=0.98,
    )
    fig.text(
        0.5,
        0.91,
        f"Participação por curva no período de {period_days} dias.",
        ha="center",
        va="top",
        fontsize=8.2,
        color="#475569",
    )
    fig.subplots_adjust(top=0.80, bottom=0.24, left=0.10, right=0.96)

    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)
    buffer.seek(0)
    return buffer


def _executive_panel_tables(products, period_days):
    status_order = [
        "RUPTURA",
        "RISCO DE RUPTURA",
        "OK",
        "ALTO",
        "EXCESSO",
        "SEM VENDA - ESTOQUE PARADO",
        "SEM VENDA / SEM ESTOQUE",
        "ESTOQUE NEGATIVO",
    ]

    total_items = len(products)
    total_stock_value = float(products["valor_estoque"].sum())

    status_summary = (
        products.groupby("status", dropna=False)
        .agg(
            Itens=("codigo", "count"),
            Estoque=("estoque", "sum"),
            Faturamento=("faturamento_periodo", "sum"),
            Valor_Estoque=("valor_estoque", "sum"),
        )
        .reindex(status_order, fill_value=0)
        .reset_index()
        .rename(
            columns={
                "status": "Status de Cobertura",
                "Estoque": "Estoque (unid.)",
                "Faturamento": f"Faturamento {period_days} dias",
                "Valor_Estoque": "Valor Estoque",
            }
        )
    )
    status_summary["% dos Itens"] = np.where(
        total_items != 0,
        status_summary["Itens"] / total_items * 100,
        0,
    )
    status_summary = status_summary[
        [
            "Status de Cobertura",
            "Itens",
            "Estoque (unid.)",
            f"Faturamento {period_days} dias",
            "% dos Itens",
            "Valor Estoque",
        ]
    ]

    abc_summary = (
        products.groupby("curva_abc", dropna=False)
        .agg(
            Itens=("codigo", "count"),
            Faturamento=("faturamento_periodo", "sum"),
            Estoque=("estoque", "sum"),
            Valor_Estoque=("valor_estoque", "sum"),
        )
        .reindex(["A", "B", "C"], fill_value=0)
        .reset_index()
        .rename(
            columns={
                "curva_abc": "Curva ABC",
                "Faturamento": f"Faturamento {period_days} dias",
                "Estoque": "Estoque (unid.)",
                "Valor_Estoque": "Valor Estoque",
            }
        )
    )

    total_revenue = float(abc_summary[f"Faturamento {period_days} dias"].sum())
    abc_summary["% Faturamento"] = np.where(
        total_revenue != 0,
        abc_summary[f"Faturamento {period_days} dias"] / total_revenue * 100,
        0,
    )
    abc_summary["Faturamento / Estoque %"] = np.where(
        abc_summary["Valor Estoque"] != 0,
        abc_summary[f"Faturamento {period_days} dias"]
        / abc_summary["Valor Estoque"]
        * 100,
        0,
    )
    abc_summary["Faturamento / Estoque total"] = np.where(
        total_stock_value != 0,
        abc_summary[f"Faturamento {period_days} dias"] / total_stock_value * 100,
        0,
    )
    abc_summary = abc_summary[
        [
            "Curva ABC",
            "Itens",
            f"Faturamento {period_days} dias",
            "% Faturamento",
            "Estoque (unid.)",
            "Valor Estoque",
            "Faturamento / Estoque %",
            "Faturamento / Estoque total",
        ]
    ]

    priority_specs = [
        (
            "Ruptura",
            products["status"].eq("RUPTURA"),
            "Priorizar reposição e revisar mínimos",
        ),
        (
            "Risco de ruptura",
            products["status"].eq("RISCO DE RUPTURA"),
            "Planejar reposição antes de entrar em ruptura",
        ),
        (
            "Estoque alto ou excessivo",
            products["status"].isin(["ALTO", "EXCESSO"]),
            "Reduzir compras e acelerar escoamento",
        ),
        (
            "Estoque parado sem venda",
            products["status"].eq("SEM VENDA - ESTOQUE PARADO"),
            "Bloquear reposição e avaliar saída do estoque",
        ),
        (
            "Saldo de estoque negativo",
            products["status"].eq("ESTOQUE NEGATIVO"),
            "Corrigir divergências de saldo no sistema",
        ),
    ]

    priority_rows = []
    for label, mask, action in priority_specs:
        subset = products.loc[mask]
        qty = int(len(subset))
        priority_rows.append(
            {
                "Prioridade Gerencial": label,
                "Quantidade": qty,
                "% dos Itens": (qty / total_items * 100) if total_items else 0,
                "Estoque (unid.)": float(subset["estoque"].sum()),
                "Ação Gerencial": action,
                "Valor Estoque": float(subset["valor_estoque"].sum()),
            }
        )

    priorities = pd.DataFrame(priority_rows)
    return status_summary, abc_summary, priorities

def formatted_xlsx_bytes(
    summary,
    products,
    raw,
    period_days,
    long_days,
    analysis_name,
    criteria,
):
    output = io.BytesIO()
    summary_export = _friendly_summary(summary, long_days)
    products_export = _friendly_products(products, long_days, period_days)
    excess_export = products_export[
        products_export["Status"].isin(["ALTO", "EXCESSO"])
    ].copy()
    stopped_export = products_export[
        products_export["Status"].eq("SEM VENDA - ESTOQUE PARADO")
    ].copy()

    total_revenue = float(products["faturamento_periodo"].sum())
    stock_value = float(products["valor_estoque"].sum())
    total_stock = float(products["estoque"].sum())
    high_mask = products["status"].isin(["ALTO", "EXCESSO"])
    stopped_mask = products["status"].eq("SEM VENDA - ESTOQUE PARADO")
    excess_value = float(products.loc[high_mask, "valor_estoque"].sum())
    stopped_value = float(products.loc[stopped_mask, "valor_estoque"].sum())
    problem_share = (
        (excess_value + stopped_value) / stock_value
        if stock_value
        else 0
    )

    revenue_col = "faturamento_analise"
    best_sales = summary.loc[summary[revenue_col].idxmax()] if not summary.empty else None
    biggest_excess = (
        summary.loc[summary["valor_alto_excesso"].idxmax()]
        if not summary.empty
        else None
    )
    biggest_stock = (
        summary.loc[summary["valor_estoque"].idxmax()]
        if not summary.empty
        else None
    )

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_export.to_excel(writer, sheet_name="RESUMO LINHAS", index=False, startrow=3)
        products_export.to_excel(writer, sheet_name="PRODUTOS", index=False, startrow=3)
        excess_export.to_excel(writer, sheet_name="ALTO EXCESSO", index=False, startrow=3)
        stopped_export.to_excel(writer, sheet_name="ESTOQUE PARADO", index=False, startrow=3)
        raw.to_excel(writer, sheet_name="DADOS BRUTOS", index=False)
        criteria_df = pd.DataFrame({
            "Critério": [
                "Período único da análise", "Curva A até", "Curva B até",
                "A - Ruptura até", "A - Risco Ruptura até", "A - OK até", "A - Alto até",
                "B - Ruptura até", "B - Risco Ruptura até", "B - OK até", "B - Alto até",
                "C - Ruptura até", "C - Risco Ruptura até", "C - OK até", "C - Alto até",
                "Cobertura/status usam o mesmo período",
            ],
            "Valor": [
                f"{int(criteria['abc_period'])} dias", f"{criteria['abc_a']:.1f}%", f"{criteria['abc_b']:.1f}%",
                f"{criteria['A_ruptura']} dias", f"{criteria['A_abaixo']} dias", f"{criteria['A_ok']} dias", f"{criteria['A_alto']} dias",
                f"{criteria['B_ruptura']} dias", f"{criteria['B_abaixo']} dias", f"{criteria['B_ok']} dias", f"{criteria['B_alto']} dias",
                f"{criteria['C_ruptura']} dias", f"{criteria['C_abaixo']} dias", f"{criteria['C_ok']} dias", f"{criteria['C_alto']} dias",
                f"{period_days} dias",
            ],
        })
        criteria_df.to_excel(writer, sheet_name="CRITERIOS", index=False)

        wb = writer.book
        ws = wb.create_sheet("DASHBOARD", 0)
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = "A4"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True

        for col in range(1, 13):
            ws.column_dimensions[get_column_letter(col)].width = 14

        ws.merge_cells("A1:L2")
        ws["A1"] = "ANÁLISE GERENCIAL DE LINHA"
        ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
        ws["A1"].font = Font(color=WHITE, bold=True, size=22)
        ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

        ws.merge_cells("A3:L3")
        ws["A3"] = f"{analysis_name}  |  Período único da análise: {period_days} dias"
        ws["A3"].fill = PatternFill("solid", fgColor=LIGHT_BLUE)
        ws["A3"].font = Font(color=NAVY, bold=True, size=11)
        ws["A3"].alignment = Alignment(horizontal="center")

        status_panel, abc_panel, priorities_panel = _executive_panel_tables(
            products,
            period_days,
        )

        for col in range(1, 16):
            ws.column_dimensions[get_column_letter(col)].width = 14

        # KPIs principais, no estilo de painel executivo compacto.
        kpi_headers = [
            "Total de Itens",
            "Curva A",
            "Curva B",
            "Curva C",
            f"Faturamento {period_days} dias",
            "Estoque (unidades)",
            "Estoque a Preço de Venda",
        ]
        curve_counts = products["curva_abc"].value_counts()
        kpi_values = [
            len(products),
            int(curve_counts.get("A", 0)),
            int(curve_counts.get("B", 0)),
            int(curve_counts.get("C", 0)),
            total_revenue,
            total_stock,
            stock_value,
        ]
        kpi_ranges = [
            (1, 2),
            (3, 4),
            (5, 6),
            (7, 8),
            (9, 10),
            (11, 12),
            (13, 15),
        ]

        for (start_col, end_col), header, value in zip(
            kpi_ranges,
            kpi_headers,
            kpi_values,
        ):
            ws.merge_cells(
                start_row=5,
                start_column=start_col,
                end_row=5,
                end_column=end_col,
            )
            ws.merge_cells(
                start_row=6,
                start_column=start_col,
                end_row=6,
                end_column=end_col,
            )
            h = ws.cell(5, start_col)
            v = ws.cell(6, start_col)
            h.value = header
            v.value = value
            h.fill = PatternFill("solid", fgColor=LIGHT_BLUE)
            h.font = Font(color=NAVY, bold=True, size=10)
            h.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            v.font = Font(color=DARK, bold=True, size=15)
            v.alignment = Alignment(horizontal="center", vertical="center")

        ws["I6"].number_format = 'R$ #,##0.00'
        ws["K6"].number_format = '#,##0.00'
        ws["M6"].number_format = 'R$ #,##0.00'

        # Títulos das duas tabelas centrais.
        ws.merge_cells("A9:F9")
        ws["A9"] = "STATUS DE COBERTURA"
        ws["A9"].fill = PatternFill("solid", fgColor=NAVY)
        ws["A9"].font = Font(color=WHITE, bold=True)

        ws.merge_cells("H9:O9")
        ws["H9"] = "CURVA ABC"
        ws["H9"].fill = PatternFill("solid", fgColor=NAVY)
        ws["H9"].font = Font(color=WHITE, bold=True)

        status_panel.to_excel(
            writer,
            sheet_name="DASHBOARD",
            index=False,
            startrow=9,
            startcol=0,
        )
        abc_panel.to_excel(
            writer,
            sheet_name="DASHBOARD",
            index=False,
            startrow=9,
            startcol=7,
        )

        _style_header(ws, 10)

        # Reaplica cabeçalho só para a tabela ABC, pois está no mesmo row.
        for col in range(8, 16):
            cell = ws.cell(10, col)
            if cell.value is not None:
                cell.fill = PatternFill("solid", fgColor=NAVY)
                cell.font = Font(color=WHITE, bold=True)
                cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True,
                )

        status_start = 11
        status_end = status_start + len(status_panel) - 1
        abc_start = 11
        abc_end = abc_start + len(abc_panel) - 1

        for row in range(status_start, status_end + 1):
            ws.cell(row, 4).number_format = 'R$ #,##0.00'
            ws.cell(row, 5).number_format = '0.0%'
            ws.cell(row, 6).number_format = 'R$ #,##0.00'

        for row in range(abc_start, abc_end + 1):
            ws.cell(row, 10).number_format = 'R$ #,##0.00'
            ws.cell(row, 11).number_format = '0.0%'
            ws.cell(row, 13).number_format = 'R$ #,##0.00'
            ws.cell(row, 14).number_format = '0.0%'
            ws.cell(row, 15).number_format = '0.0%'

        priority_title_row = max(status_end, abc_end) + 3
        ws.merge_cells(
            start_row=priority_title_row,
            start_column=1,
            end_row=priority_title_row,
            end_column=15,
        )
        ws.cell(priority_title_row, 1).value = "PRIORIDADES GERENCIAIS"
        ws.cell(priority_title_row, 1).fill = PatternFill("solid", fgColor=NAVY)
        ws.cell(priority_title_row, 1).font = Font(color=WHITE, bold=True)

        priorities_panel.to_excel(
            writer,
            sheet_name="DASHBOARD",
            index=False,
            startrow=priority_title_row,
            startcol=0,
        )
        priority_header_row = priority_title_row + 1
        _style_header(ws, priority_header_row)

        priority_data_start = priority_header_row + 1
        priority_data_end = priority_data_start + len(priorities_panel) - 1
        for row in range(priority_data_start, priority_data_end + 1):
            ws.cell(row, 3).number_format = '0.0%'
            ws.cell(row, 6).number_format = 'R$ #,##0.00'

        ws.freeze_panes = "A10"

        # Demais abas.
        for sheet_name in ("RESUMO LINHAS", "PRODUTOS", "ALTO EXCESSO", "ESTOQUE PARADO"):
            s = wb[sheet_name]
            s.sheet_view.showGridLines = False
            s.merge_cells(start_row=1, start_column=1, end_row=1, end_column=s.max_column)
            s["A1"] = (
                "RESUMO GERENCIAL POR LINHA"
                if sheet_name == "RESUMO LINHAS"
                else sheet_name
            )
            s["A1"].fill = PatternFill("solid", fgColor=NAVY)
            s["A1"].font = Font(color=WHITE, bold=True, size=16)
            s["A1"].alignment = Alignment(horizontal="center")
            s.merge_cells(start_row=2, start_column=1, end_row=2, end_column=s.max_column)
            s["A2"] = f"{analysis_name} | Período principal: {period_days} dias"
            s["A2"].fill = PatternFill("solid", fgColor=LIGHT_BLUE)
            s["A2"].font = Font(color=NAVY, italic=True)
            s["A2"].alignment = Alignment(horizontal="center")

        _format_sheet(
            wb["RESUMO LINHAS"],
            header_row=4,
            table_name="TabelaResumoLinhas",
            currency_headers={
                "Faturamento 90d",
                f"Faturamento {long_days}d",
                "Valor Estoque",
                "Valor Alto/Excesso",
                "Valor Parado",
            },
            percent_headers={
                "% SKUs",
                "% Fat. 90d",
                f"% Fat. {long_days}d",
                "% Estoque",
            },
        )

        _format_sheet(
            wb["PRODUTOS"],
            header_row=4,
            table_name="TabelaProdutos",
            currency_headers={
                "Preço Venda",
                f"Faturamento {period_days}d",
                "Valor Estoque",
            },
            percent_headers={"Participação Acumulada"},
            decimal_headers={"Cobertura (dias)"},
            status_header="Status",
            curve_header="Curva ABC",
        )

        _format_sheet(
            wb["ALTO EXCESSO"],
            header_row=4,
            table_name="TabelaAltoExcesso",
            currency_headers={
                "Preço Venda",
                f"Faturamento {period_days}d",
                "Valor Estoque",
            },
            percent_headers={"Participação Acumulada"},
            decimal_headers={"Cobertura (dias)"},
            status_header="Status",
            curve_header="Curva ABC",
        )

        _format_sheet(
            wb["ESTOQUE PARADO"],
            header_row=4,
            table_name="TabelaEstoqueParado",
            currency_headers={
                "Preço Venda",
                f"Faturamento {period_days}d",
                "Valor Estoque",
            },
            percent_headers={"Participação Acumulada"},
            decimal_headers={"Cobertura (dias)"},
            status_header="Status",
            curve_header="Curva ABC",
        )

        raw_ws = wb["DADOS BRUTOS"]
        raw_ws.sheet_view.showGridLines = False
        raw_ws.freeze_panes = "A2"
        _style_header(raw_ws, 1)
        _auto_width(raw_ws)
        raw_ws.auto_filter.ref = raw_ws.dimensions

        crit_ws = wb["CRITERIOS"]
        crit_ws.sheet_view.showGridLines = False
        crit_ws.freeze_panes = "A2"
        _style_header(crit_ws, 1)
        _auto_width(crit_ws, min_width=18, max_width=38)
        crit_ws.column_dimensions["A"].width = 34
        crit_ws.column_dimensions["B"].width = 22

        # Escala visual na tabela gerencial.
        resumo_ws = wb["RESUMO LINHAS"]
        header_map = {
            resumo_ws.cell(4, c).value: c
            for c in range(1, resumo_ws.max_column + 1)
        }
        if "Valor Alto/Excesso" in header_map and resumo_ws.max_row >= 5:
            col = get_column_letter(header_map["Valor Alto/Excesso"])
            cell_range = f"{col}5:{col}{resumo_ws.max_row}"
            resumo_ws.conditional_formatting.add(
                cell_range,
                ColorScaleRule(
                    start_type="min",
                    start_color="E2F0D9",
                    mid_type="percentile",
                    mid_value=50,
                    mid_color="FFF2CC",
                    end_type="max",
                    end_color="F4CCCC",
                ),
            )

    return output.getvalue()


def _get_secret(name, default=""):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def _github_persistence_settings():
    repo = _get_secret("GITHUB_REPO", DEFAULT_GITHUB_REPO)
    branch = _get_secret("GITHUB_BRANCH", DEFAULT_GITHUB_BRANCH)
    token = _get_secret("GITHUB_TOKEN", "")
    return str(repo), str(branch), str(token)


def _github_headers(token=""):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "planejamento-pedidos-streamlit",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_read_config():
    repo, branch, token = _github_persistence_settings()
    encoded_path = urllib.parse.quote(PERSISTENT_CRITERIA_FILE, safe="/")
    encoded_branch = urllib.parse.quote(branch, safe="")
    url = (
        f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
        f"?ref={encoded_branch}"
    )
    request = urllib.request.Request(
        url,
        headers=_github_headers(token),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        return None, f"GitHub respondeu HTTP {exc.code} ao carregar o padrão."
    except Exception as exc:
        return None, f"Não foi possível carregar o padrão permanente: {exc}"

    try:
        content = base64.b64decode(payload["content"]).decode("utf-8")
        saved = json.loads(content)
        merged = {**DEFAULT_CRITERIA, **saved}
        if _criteria_errors(merged):
            return None, "O padrão salvo no GitHub está inválido e foi ignorado."
        return merged, None
    except Exception as exc:
        return None, f"Não foi possível interpretar o padrão salvo: {exc}"


def _github_save_config(criteria):
    repo, branch, token = _github_persistence_settings()
    if not token:
        return (
            False,
            "Falta configurar GITHUB_TOKEN nos Secrets do Streamlit para gravar no GitHub.",
        )

    encoded_path = urllib.parse.quote(PERSISTENT_CRITERIA_FILE, safe="/")
    encoded_branch = urllib.parse.quote(branch, safe="")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"

    sha = None
    get_url = f"{url}?ref={encoded_branch}"
    get_request = urllib.request.Request(
        get_url,
        headers=_github_headers(token),
        method="GET",
    )
    try:
        with urllib.request.urlopen(get_request, timeout=10) as response:
            existing = json.loads(response.read().decode("utf-8"))
            sha = existing.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return False, f"GitHub respondeu HTTP {exc.code} ao localizar o arquivo de padrão."
    except Exception as exc:
        return False, f"Não foi possível localizar o padrão atual no GitHub: {exc}"

    content = json.dumps(criteria, ensure_ascii=False, indent=2, sort_keys=True)
    payload = {
        "message": "Atualiza critérios padrão da análise de linha",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    body = json.dumps(payload).encode("utf-8")
    put_request = urllib.request.Request(
        url,
        data=body,
        headers={
            **_github_headers(token),
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(put_request, timeout=15) as response:
            response.read()
        return True, "Critérios salvos como padrão permanente."
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message", "")
        except Exception:
            detail = ""
        suffix = f" — {detail}" if detail else ""
        return False, f"GitHub respondeu HTTP {exc.code} ao salvar{suffix}."
    except Exception as exc:
        return False, f"Não foi possível salvar o padrão permanente: {exc}"


def _criteria_errors(criteria):
    errors = []
    if int(criteria["abc_period"]) < 1:
        errors.append("O período da análise deve ser maior que zero.")
    if not (0 < float(criteria["abc_a"]) < float(criteria["abc_b"]) <= 100):
        errors.append("Os cortes da Curva ABC devem seguir A < B e B ≤ 100%.")
    for curve in ("A", "B", "C"):
        if not (
            float(criteria[f"{curve}_ruptura"]) < float(criteria[f"{curve}_abaixo"])
            < float(criteria[f"{curve}_ok"]) < float(criteria[f"{curve}_alto"])
        ):
            errors.append(
                f"Curva {curve}: os limites devem crescer na ordem "
                "Ruptura < Risco Ruptura < OK < Alto."
            )
    return errors


def render_analise_linha():
    st.title("📊 Análise Gerencial de Linha")
    st.caption(
        "Painel executivo com faturamento, estoque, Curva ABC, cobertura, excesso "
        "e produtos parados — direto do relatório bruto do sistema."
    )

    st.markdown("### Importação do relatório")

    col_import, col_modelo = st.columns([2.2, 1])
    with col_import:
        uploaded = st.file_uploader(
            "Importe o relatório bruto por marca",
            type=["xlsx", "xls", "csv"],
            key="linha_raw_v2",
            help="Use o relatório no formato esperado pelo NEXO. Se tiver dúvida, baixe o modelo ao lado.",
        )

    with col_modelo:
        st.markdown("**Primeira vez usando?**")
        st.download_button(
            "📥 Baixar modelo de importação",
            data=line_import_template_bytes(),
            file_name="NEXO_modelo_importacao_analise_linha.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_modelo_analise_linha",
        )

    with st.expander("📘 Como preparar o arquivo para a Análise de Linha"):
        st.markdown(
            """
            **Para evitar erros na importação:**

            - use o modelo oficial disponibilizado acima;
            - mantenha os nomes dos cabeçalhos;
            - coloque **um produto por linha**;
            - informe código, descrição, referência, código da linha e nome da linha;
            - estoque, mínimo, vendas e preço devem ser valores numéricos;
            - mantenha as vendas acumuladas de **30, 60, 90 e 360/365 dias**;
            - não coloque totais ou subtotais no meio da base;
            - consulte as abas **INSTRUCOES**, **DICIONARIO** e **EXEMPLO** dentro do arquivo modelo.

            O NEXO valida o relatório antes da análise e informa exatamente quais colunas obrigatórias estão faltando.
            """
        )

    if not uploaded:
        st.info(
            "Envie o relatório bruto para montar o dashboard gerencial. "
            "Se for a primeira utilização, baixe o modelo e consulte as instruções."
        )
        return

    try:
        raw = read_file(uploaded)
        base, long_days = standardize_line_report(raw)
    except Exception as exc:
        st.error(str(exc))
        return

    analysis_name = st.text_input(
        "Nome da análise / marca",
        value=uploaded.name.rsplit(".", 1)[0],
        key="nome_analise_linha_v2",
    )

    if "line_criteria_persistent_loaded" not in st.session_state:
        persistent_criteria, persistent_error = _github_read_config()
        loaded = persistent_criteria or DEFAULT_CRITERIA.copy()
        st.session_state["line_criteria_saved"] = {
            **DEFAULT_CRITERIA,
            **loaded,
        }
        st.session_state["line_criteria_active"] = st.session_state["line_criteria_saved"].copy()
        st.session_state["line_criteria_persistent_loaded"] = True
        if persistent_error:
            st.session_state["line_criteria_feedback"] = persistent_error
    else:
        st.session_state["line_criteria_saved"] = {
            **DEFAULT_CRITERIA,
            **st.session_state.get("line_criteria_saved", {}),
        }
        st.session_state["line_criteria_active"] = {
            **DEFAULT_CRITERIA,
            **st.session_state.get("line_criteria_active", {}),
        }

    if _criteria_errors(st.session_state["line_criteria_saved"]):
        st.session_state["line_criteria_saved"] = DEFAULT_CRITERIA.copy()
    if _criteria_errors(st.session_state["line_criteria_active"]):
        st.session_state["line_criteria_active"] = st.session_state["line_criteria_saved"].copy()

    widget_defaults = st.session_state["line_criteria_saved"]
    widget_keys = {
        "abc_period": "crit5_abc_period", "abc_a": "crit5_abc_a", "abc_b": "crit5_abc_b",
        "A_ruptura": "crit5_A_ruptura", "A_abaixo": "crit5_A_abaixo", "A_ok": "crit5_A_ok", "A_alto": "crit5_A_alto",
        "B_ruptura": "crit5_B_ruptura", "B_abaixo": "crit5_B_abaixo", "B_ok": "crit5_B_ok", "B_alto": "crit5_B_alto",
        "C_ruptura": "crit5_C_ruptura", "C_abaixo": "crit5_C_abaixo", "C_ok": "crit5_C_ok", "C_alto": "crit5_C_alto",
    }
    for name, key in widget_keys.items():
        if key not in st.session_state:
            st.session_state[key] = widget_defaults[name]

    def collect_criteria_state():
        return {name: st.session_state[key] for name, key in widget_keys.items()}

    def auto_apply_criteria():
        current = collect_criteria_state()
        errors = _criteria_errors(current)
        if errors:
            st.session_state["line_criteria_feedback"] = " | ".join(errors)
            return
        st.session_state["line_criteria_active"] = current.copy()
        st.session_state["line_criteria_feedback"] = ""

    def save_criteria():
        current = collect_criteria_state()
        errors = _criteria_errors(current)
        if errors:
            st.session_state["line_criteria_feedback"] = " | ".join(errors)
            return

        st.session_state["line_criteria_active"] = current.copy()
        ok, message = _github_save_config(current)
        if ok:
            st.session_state["line_criteria_saved"] = current.copy()
        st.session_state["line_criteria_feedback"] = message

    def reset_criteria():
        st.session_state["line_criteria_active"] = DEFAULT_CRITERIA.copy()
        st.session_state["line_criteria_saved"] = DEFAULT_CRITERIA.copy()
        st.session_state["line_criteria_feedback"] = "Critérios restaurados para o padrão."
        for name, key in widget_keys.items():
            st.session_state[key] = DEFAULT_CRITERIA[name]

    with st.sidebar:
        st.markdown("---")
        st.subheader("⚙️ Critérios da análise")
        st.caption("Configure aqui a Curva ABC e os dias de cobertura. Alterações válidas recalculam a análise automaticamente.")

        st.markdown("**Curva ABC**")
        st.number_input(
            "Período da análise (dias)",
            min_value=1,
            max_value=3650,
            step=1,
            key=widget_keys["abc_period"],
            on_change=auto_apply_criteria,
            help="Digite qualquer período em dias. O mesmo período será usado para Curva ABC, cobertura e status.",
        )
        st.caption(
            f"O relatório possui históricos de 30, 60, 90 e {long_days} dias. "
            "Períodos intermediários são estimados proporcionalmente entre esses pontos."
        )
        st.number_input(
            "Curva A até (%)",
            min_value=1.0,
            max_value=99.0,
            step=1.0,
            key=widget_keys["abc_a"],
            on_change=auto_apply_criteria,
        )
        st.number_input(
            "Curva B até (%)",
            min_value=2.0,
            max_value=100.0,
            step=1.0,
            key=widget_keys["abc_b"],
            on_change=auto_apply_criteria,
        )
        st.caption("Curva C = acima do limite da Curva B.")

        with st.expander("Curva A — status por dias", expanded=True):
            st.number_input(
                "RUPTURA: abaixo de (dias)",
                min_value=0,
                step=1,
                key=widget_keys["A_ruptura"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "RISCO RUPTURA: abaixo de (dias)",
                min_value=1,
                step=1,
                key=widget_keys["A_abaixo"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "OK: até (dias)",
                min_value=1,
                step=1,
                key=widget_keys["A_ok"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "ALTO: até (dias)",
                min_value=1,
                step=1,
                key=widget_keys["A_alto"],
                on_change=auto_apply_criteria,
            )
            st.caption("Acima do limite de ALTO = EXCESSO.")

        with st.expander("Curva B — status por dias", expanded=False):
            st.number_input(
                "RUPTURA: abaixo de (dias)",
                min_value=0,
                step=1,
                key=widget_keys["B_ruptura"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "RISCO RUPTURA: abaixo de (dias)",
                min_value=1,
                step=1,
                key=widget_keys["B_abaixo"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "OK: até (dias)",
                min_value=1,
                step=1,
                key=widget_keys["B_ok"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "ALTO: até (dias)",
                min_value=1,
                step=1,
                key=widget_keys["B_alto"],
                on_change=auto_apply_criteria,
            )
            st.caption("Acima do limite de ALTO = EXCESSO.")

        with st.expander("Curva C — status por dias", expanded=False):
            st.number_input(
                "RUPTURA: abaixo de (dias)",
                min_value=0,
                step=1,
                key=widget_keys["C_ruptura"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "RISCO RUPTURA: abaixo de (dias)",
                min_value=1,
                step=1,
                key=widget_keys["C_abaixo"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "OK: até (dias)",
                min_value=1,
                step=1,
                key=widget_keys["C_ok"],
                on_change=auto_apply_criteria,
            )
            st.number_input(
                "ALTO: até (dias)",
                min_value=1,
                step=1,
                key=widget_keys["C_alto"],
                on_change=auto_apply_criteria,
            )
            st.caption("Acima do limite de ALTO = EXCESSO.")

        st.button(
            "💾 Salvar como padrão permanente",
            use_container_width=True,
            on_click=save_criteria,
        )
        st.button(
            "↩️ Restaurar padrão",
            use_container_width=True,
            on_click=reset_criteria,
        )

        _, _, github_token = _github_persistence_settings()
        if github_token:
            st.caption("✅ Salvamento permanente habilitado via GitHub.")
        else:
            st.caption("ℹ️ Para persistir após reboot, configure GITHUB_TOKEN nos Secrets do Streamlit.")

        feedback = st.session_state.get("line_criteria_feedback", "")
        if feedback:
            if "salvos como padrão permanente" in feedback.lower() or "restaurados" in feedback.lower():
                st.success(feedback)
            else:
                st.warning(feedback)

    criteria = st.session_state["line_criteria_active"].copy()
    period_days = int(criteria["abc_period"])

    st.info(
        f"⚙️ **Critérios no menu lateral** — Período único da análise: "
        f"**{period_days} dias** • A até **{criteria['abc_a']:.0f}%** • "
        f"B até **{criteria['abc_b']:.0f}%**. O mesmo período define Curva ABC, cobertura e status."
    )

    products, summary = build_line_analysis(base, period_days, criteria, long_days)
    revenue_col = "faturamento_analise"

    total_revenue = float(products["faturamento_periodo"].sum())
    total_stock = float(products["estoque"].sum())
    stock_value = float(products["valor_estoque"].sum())
    high_mask = products["status"].isin(["ALTO", "EXCESSO"])
    stopped_mask = products["status"].eq("SEM VENDA - ESTOQUE PARADO")
    dangerous_mask = products["status"].eq("RUPTURA")
    excess_value = float(products.loc[high_mask, "valor_estoque"].sum())
    stopped_value = float(products.loc[stopped_mask, "valor_estoque"].sum())
    problem_share = (
        (excess_value + stopped_value) / stock_value
        if stock_value
        else 0
    )

    status_panel, abc_panel, priorities_panel = _executive_panel_tables(
        products,
        period_days,
    )

    st.markdown("### Painel gerencial")

    curve_counts = products["curva_abc"].value_counts()
    top1, top2, top3, top4 = st.columns(4)
    top1.metric("Total de Itens", integer(len(products)))
    top2.metric("Curva A", integer(curve_counts.get("A", 0)))
    top3.metric("Curva B", integer(curve_counts.get("B", 0)))
    top4.metric("Curva C", integer(curve_counts.get("C", 0)))

    fin1, fin2, fin3 = st.columns(3)
    fin1.metric(f"Faturamento {period_days} dias", brl(total_revenue))
    fin2.metric("Estoque (unidades)", integer(total_stock))
    fin3.metric("Estoque a Preço de Venda", brl(stock_value))

    left_panel, right_panel = st.columns([1, 1.25])

    with left_panel:
        st.markdown("#### Status de Cobertura")
        st.dataframe(
            status_panel,
            use_container_width=True,
            hide_index=True,
            column_config={
                f"Faturamento {period_days} dias": st.column_config.NumberColumn(
                    format="R$ %.2f"
                ),
                "% dos Itens": st.column_config.NumberColumn(format="%.1f%%"),
                "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

    with right_panel:
        st.markdown("#### Curva ABC")
        st.dataframe(
            abc_panel,
            use_container_width=True,
            hide_index=True,
            column_config={
                f"Faturamento {period_days} dias": st.column_config.NumberColumn(
                    format="R$ %.2f"
                ),
                "% Faturamento": st.column_config.NumberColumn(format="%.1f%%"),
                "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
                "Faturamento / Estoque %": st.column_config.NumberColumn(
                    format="%.1f%%"
                ),
                "Faturamento / Estoque total": st.column_config.NumberColumn(
                    format="%.1f%%"
                ),
            },
        )

    st.markdown("#### Prioridades Gerenciais")
    st.dataframe(
        priorities_panel,
        use_container_width=True,
        hide_index=True,
        column_config={
            "% dos Itens": st.column_config.NumberColumn(format="%.1f%%"),
            "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

    with st.expander("Ver gráficos", expanded=False):
        line_domain = summary["linha"].tolist()
        line_colors = [
            LINE_CHART_COLORS[i % len(LINE_CHART_COLORS)]
            for i in range(len(line_domain))
        ]

        abc_rep = (
            products.groupby("curva_abc", dropna=False)
            .agg(
                faturamento=("faturamento_periodo", "sum"),
                valor_estoque=("valor_estoque", "sum"),
            )
            .reindex(["A", "B", "C"], fill_value=0)
            .reset_index()
            .rename(columns={"curva_abc": "Curva"})
        )

        total_abc_faturamento = float(abc_rep["faturamento"].sum())
        total_abc_estoque = float(abc_rep["valor_estoque"].sum())
        abc_rep["% Vendas"] = np.where(
            total_abc_faturamento != 0,
            abc_rep["faturamento"] / total_abc_faturamento * 100,
            0,
        )
        abc_rep["% Valor Estoque"] = np.where(
            total_abc_estoque != 0,
            abc_rep["valor_estoque"] / total_abc_estoque * 100,
            0,
        )

        abc_chart_vendas = abc_rep[
            ["Curva", "% Vendas", "faturamento"]
        ].copy()
        abc_chart_vendas.columns = ["Curva", "Percentual", "Valor"]
        abc_chart_vendas["Indicador"] = "Valor vendido"

        abc_chart_estoque = abc_rep[
            ["Curva", "% Valor Estoque", "valor_estoque"]
        ].copy()
        abc_chart_estoque.columns = ["Curva", "Percentual", "Valor"]
        abc_chart_estoque["Indicador"] = "Valor do estoque"

        abc_chart = pd.concat(
            [abc_chart_vendas, abc_chart_estoque],
            ignore_index=True,
        )
        abc_chart["Valor em R$"] = abc_chart["Valor"].apply(brl)

        abc_compare_spec = {
            "mark": {
                "type": "bar",
                "cornerRadiusTopLeft": 3,
                "cornerRadiusTopRight": 3,
            },
            "encoding": {
                "x": {
                    "field": "Curva",
                    "type": "nominal",
                    "sort": ["A", "B", "C"],
                    "title": "Curva ABC",
                    "axis": {"labelAngle": 0},
                },
                "xOffset": {"field": "Indicador"},
                "y": {
                    "field": "Percentual",
                    "type": "quantitative",
                    "title": "Participação (%)",
                    "scale": {"domain": [0, 100]},
                },
                "color": {
                    "field": "Indicador",
                    "type": "nominal",
                    "title": None,
                    "legend": {"orient": "bottom"},
                },
                "tooltip": [
                    {"field": "Curva", "type": "nominal", "title": "Curva"},
                    {"field": "Indicador", "type": "nominal", "title": "Indicador"},
                    {
                        "field": "Percentual",
                        "type": "quantitative",
                        "title": "Participação (%)",
                        "format": ".1f",
                    },
                    {
                        "field": "Valor em R$",
                        "type": "nominal",
                        "title": "Valor (R$)",
                    },
                ],
            },
            "view": {"stroke": None},
        }

        graph1, graph2 = st.columns(2)
        with graph1:
            revenue_pie = summary[["linha", revenue_col]].copy()
            _pie_chart(
                revenue_pie,
                "linha",
                revenue_col,
                f"Faturamento por linha — {period_days} dias",
                "Onde as vendas estão concentradas.",
                "Faturamento",
                color_domain=line_domain,
                color_range=line_colors,
            )

        with graph2:
            st.markdown("**Curva ABC — vendas x estoque**")
            st.caption(
                "Passe o mouse nas barras para ver participação e valor em R$."
            )
            st.vega_lite_chart(
                abc_chart,
                abc_compare_spec,
                use_container_width=True,
            )

    with st.expander("Ver ranking gerencial por linha", expanded=False):
        manager = _friendly_summary(summary, long_days)[
            [
                "Linha",
                "SKUs",
                "Faturamento 90d",
                f"Faturamento {long_days}d",
                "Valor Estoque",
                "Valor Alto/Excesso",
                "Valor Parado",
                "Ruptura",
                "Excesso",
                "Parados",
            ]
        ].copy()
        st.dataframe(
            manager,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Faturamento 90d": st.column_config.NumberColumn(format="R$ %.2f"),
                f"Faturamento {long_days}d": st.column_config.NumberColumn(
                    format="R$ %.2f"
                ),
                "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Alto/Excesso": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Parado": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

    st.markdown("### Análise por Curva ABC")
    st.caption(
        "Veja, dentro de cada curva, quantos produtos estão em cada status, "
        "o valor de estoque correspondente e quais são os itens."
    )

    abc_status_order = [
        "EXCESSO",
        "ALTO",
        "OK",
        "RISCO DE RUPTURA",
        "RUPTURA",
    ]

    curva_a_tab, curva_b_tab, curva_c_tab = st.tabs(
        ["Curva A", "Curva B", "Curva C"]
    )

    for curva_nome, curva_tab in zip(
        ["A", "B", "C"],
        [curva_a_tab, curva_b_tab, curva_c_tab],
    ):
        with curva_tab:
            curva_df = products[
                products["curva_abc"].eq(curva_nome)
                & products["status"].isin(abc_status_order)
            ].copy()

            total_curva_itens = len(curva_df)
            total_curva_valor = float(curva_df["valor_estoque"].sum())

            kpi1, kpi2 = st.columns(2)
            kpi1.metric(
                f"Itens Curva {curva_nome}",
                integer(total_curva_itens),
            )
            kpi2.metric(
                "Valor de estoque",
                brl(total_curva_valor),
            )

            resumo_status = (
                curva_df.groupby("status", dropna=False)
                .agg(
                    Itens=("codigo", "count"),
                    Valor_Estoque=("valor_estoque", "sum"),
                )
                .reindex(abc_status_order, fill_value=0)
                .reset_index()
                .rename(
                    columns={
                        "status": "Status",
                        "Valor_Estoque": "Valor Estoque",
                    }
                )
            )
            resumo_status["% Valor da Curva"] = np.where(
                total_curva_valor != 0,
                resumo_status["Valor Estoque"] / total_curva_valor * 100,
                0,
            )

            st.dataframe(
                resumo_status,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Itens": st.column_config.NumberColumn(format="%d"),
                    "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
                    "% Valor da Curva": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            status_escolhido = st.selectbox(
                "Mostrar produtos",
                ["Todos os status"] + abc_status_order,
                key=f"abc_status_produtos_{curva_nome}",
            )

            itens_curva = curva_df.copy()
            if status_escolhido != "Todos os status":
                itens_curva = itens_curva[
                    itens_curva["status"].eq(status_escolhido)
                ].copy()

            itens_view = _friendly_products(
                itens_curva,
                long_days,
                period_days,
            )[
                [
                    "Código",
                    "Referência",
                    "Descrição",
                    "Linha",
                    "Estoque",
                    f"Faturamento {period_days}d",
                    "Cobertura (dias)",
                    "Status",
                    "Valor Estoque",
                ]
            ].copy()

            st.caption(
                f"{len(itens_view)} produto(s) exibido(s)"
                + (
                    f" em {status_escolhido}"
                    if status_escolhido != "Todos os status"
                    else ""
                )
                + "."
            )

            st.dataframe(
                itens_view,
                use_container_width=True,
                hide_index=True,
                column_config={
                    f"Faturamento {period_days}d": st.column_config.NumberColumn(
                        format="R$ %.2f"
                    ),
                    "Cobertura (dias)": st.column_config.NumberColumn(
                        format="%.1f"
                    ),
                    "Valor Estoque": st.column_config.NumberColumn(
                        format="R$ %.2f"
                    ),
                },
            )

    st.markdown("### Detalhamento")
    selected_line = st.selectbox(
        "Escolha uma linha para detalhar",
        ["Todas as linhas"] + summary["linha"].tolist(),
        key="linha_detalhe_v2",
    )
    products_filtered = products.copy()
    if selected_line != "Todas as linhas":
        products_filtered = products_filtered[
            products_filtered["linha"].eq(selected_line)
        ].copy()

    if selected_line != "Todas as linhas":
        line_revenue = float(products_filtered["faturamento_periodo"].sum())
        line_stock = float(products_filtered["valor_estoque"].sum())
        line_high = products_filtered["status"].isin(["ALTO", "EXCESSO"])
        line_stopped = products_filtered["status"].eq("SEM VENDA - ESTOQUE PARADO")
        dcols = st.columns(4)
        dcols[0].metric("SKUs da linha", len(products_filtered))
        dcols[1].metric(f"Faturamento {period_days}d", brl(line_revenue))
        dcols[2].metric("Valor estoque", brl(line_stock))
        dcols[3].metric(
            "Valor Alto/Excesso",
            brl(products_filtered.loc[line_high, "valor_estoque"].sum()),
        )

    tab1, tab2, tab3 = st.tabs(
        ["Produtos críticos", "Todos os produtos", "Critérios"]
    )

    with tab1:
        crit_kind = st.radio(
            "Visualizar",
            ["Ruptura / Risco", "Alto / Excesso", "Estoque parado"],
            horizontal=True,
            key="criticos_v2",
        )
        if crit_kind == "Ruptura / Risco":
            filtered = products_filtered[
                products_filtered["status"].isin(["RUPTURA", "RISCO DE RUPTURA"])
            ].copy()
        elif crit_kind == "Alto / Excesso":
            filtered = products_filtered[
                products_filtered["status"].isin(["ALTO", "EXCESSO"])
            ].copy()
        else:
            filtered = products_filtered[
                products_filtered["status"].eq("SEM VENDA - ESTOQUE PARADO")
            ].copy()

        critical_view = _friendly_products(filtered, long_days, period_days)[
            [
                "Código",
                "Referência",
                "Descrição",
                "Linha",
                "Estoque",
                "Vendas 90d",
                f"Vendas {long_days}d",
                "Curva ABC",
                "Cobertura (dias)",
                "Status",
                "Valor Estoque",
            ]
        ]
        st.dataframe(
            critical_view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
                "Cobertura (dias)": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    with tab2:
        f1, f2 = st.columns(2)
        curves = f1.multiselect(
            "Curva ABC",
            ["A", "B", "C"],
            default=["A", "B", "C"],
            key="filtro_curva_v2",
        )
        statuses = sorted(products_filtered["status"].dropna().unique().tolist())
        selected_status = f2.multiselect(
            "Status",
            statuses,
            default=statuses,
            key="filtro_status_v2",
        )
        detail = products_filtered[
            products_filtered["curva_abc"].isin(curves)
            & products_filtered["status"].isin(selected_status)
        ].copy()
        product_view = _friendly_products(detail, long_days, period_days)
        product_view["Participação Acumulada"] = product_view["Participação Acumulada"] * 100
        st.dataframe(
            product_view,
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

    with tab3:
        st.markdown(f"**Período único:** **{period_days} dias** para Curva ABC, cobertura e status. A até **{criteria['abc_a']:.0f}%**, B até **{criteria['abc_b']:.0f}%**, C acima disso.")
        st.markdown(
            f"**Curva A:** <{criteria['A_ruptura']} dias RUPTURA; "
            f"{criteria['A_ruptura']}–<{criteria['A_abaixo']} RISCO RUPTURA; "
            f"{criteria['A_abaixo']}–{criteria['A_ok']} OK; "
            f">{criteria['A_ok']}–{criteria['A_alto']} ALTO; >{criteria['A_alto']} EXCESSO."
        )
        st.markdown(
            f"**Curva B:** <{criteria['B_ruptura']} dias RUPTURA; "
            f"{criteria['B_ruptura']}–<{criteria['B_abaixo']} RISCO RUPTURA; "
            f"{criteria['B_abaixo']}–{criteria['B_ok']} OK; "
            f">{criteria['B_ok']}–{criteria['B_alto']} ALTO; >{criteria['B_alto']} EXCESSO."
        )
        st.markdown(
            f"**Curva C:** <{criteria['C_ruptura']} dias RUPTURA; "
            f"{criteria['C_ruptura']}–<{criteria['C_abaixo']} RISCO RUPTURA; "
            f"{criteria['C_abaixo']}–{criteria['C_ok']} OK; "
            f">{criteria['C_ok']}–{criteria['C_alto']} ALTO; >{criteria['C_alto']} EXCESSO."
        )
        st.caption("Produto sem venda e com saldo positivo é classificado como Estoque parado. Estoque negativo permanece em classificação própria.")

    export = formatted_xlsx_bytes(
        summary=summary,
        products=products,
        raw=raw,
        period_days=period_days,
        long_days=long_days,
        analysis_name=analysis_name,
        criteria=criteria,
    )

    st.download_button(
        "📊 Baixar relatório gerencial formatado (.xlsx)",
        data=export,
        file_name=f"analise_gerencial_linha_{period_days}d.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        key="download_analise_gerencial_v2",
    )

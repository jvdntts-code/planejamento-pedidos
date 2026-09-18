import io
import re
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st

from openpyxl.chart import BarChart, DoughnutChart, Reference
from openpyxl.chart.label import DataLabelList
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
    if stock < 0:
        return "ESTOQUE NEGATIVO"
    if sales <= 0:
        return "SEM VENDA - ESTOQUE PARADO" if stock > 0 else "SEM VENDA / SEM ESTOQUE"

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
        "PERIGOSO": "perigoso",
        "ABAIXO DO RECOMENDADO": "abaixo_recomendado",
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

    sort_col = "faturamento_90" if period_days == 90 else "faturamento_longo"
    summary = summary.sort_values(sort_col, ascending=False).reset_index(drop=True)
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
            "perigoso",
            "abaixo_recomendado",
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
        "Perigoso",
        "Abaixo Recomend.",
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
        "PERIGOSO": PatternFill("solid", fgColor=LIGHT_RED),
        "ABAIXO DO RECOMENDADO": PatternFill("solid", fgColor=LIGHT_YELLOW),
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
    if table_name:
        _add_excel_table(ws, header_row, table_name)

    ws.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(ws.max_column)}{ws.max_row}"
    )


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


def formatted_xlsx_bytes(
    summary,
    products,
    raw,
    period_days,
    long_days,
    analysis_name,
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

    revenue_col = "faturamento_90" if period_days == 90 else "faturamento_longo"
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
        ws["A3"] = f"{analysis_name}  |  Período principal: {period_days} dias"
        ws["A3"].fill = PatternFill("solid", fgColor=LIGHT_BLUE)
        ws["A3"].font = Font(color=NAVY, bold=True, size=11)
        ws["A3"].alignment = Alignment(horizontal="center")

        _write_card(ws, 1, 3, 5, "SKUs analisados", len(products), LIGHT_BLUE)
        _write_card(ws, 4, 6, 5, f"Faturamento {period_days}d", total_revenue, LIGHT_GREEN)
        ws["D6"].number_format = 'R$ #,##0.00'
        _write_card(ws, 7, 9, 5, "Valor do estoque", stock_value, LIGHT_YELLOW)
        ws["G6"].number_format = 'R$ #,##0.00'
        _write_card(ws, 10, 12, 5, "Estoque total (un.)", total_stock, "EDEDED")

        _write_card(ws, 1, 3, 9, "Itens Alto / Excesso", int(high_mask.sum()), LIGHT_ORANGE)
        _write_card(ws, 4, 6, 9, "Valor Alto / Excesso", excess_value, "FCE4D6")
        ws["D10"].number_format = 'R$ #,##0.00'
        _write_card(ws, 7, 9, 9, "Valor parado", stopped_value, "D9D9D9")
        ws["G10"].number_format = 'R$ #,##0.00'
        _write_card(ws, 10, 12, 9, "% estoque em atenção", problem_share, "F4CCCC")
        ws["J10"].number_format = '0.0%'

        ws.merge_cells("A13:L13")
        ws["A13"] = "RESUMO EXECUTIVO"
        ws["A13"].fill = PatternFill("solid", fgColor=NAVY)
        ws["A13"].font = Font(color=WHITE, bold=True, size=12)
        ws["A13"].alignment = Alignment(horizontal="left")

        executive_lines = []
        if best_sales is not None:
            share = float(best_sales[revenue_col]) / total_revenue if total_revenue else 0
            executive_lines.append(
                f"• Maior faturamento: {best_sales['linha']} — {brl(best_sales[revenue_col])} ({share:.1%} do total)."
            )
        if biggest_excess is not None:
            executive_lines.append(
                f"• Maior concentração em Alto/Excesso: {biggest_excess['linha']} — {brl(biggest_excess['valor_alto_excesso'])}."
            )
        if biggest_stock is not None:
            executive_lines.append(
                f"• Maior valor de estoque: {biggest_stock['linha']} — {brl(biggest_stock['valor_estoque'])}."
            )
        executive_lines.append(
            f"• Estoque em itens Alto/Excesso + Parados representa {problem_share:.1%} do valor total de estoque."
        )
        for offset, line in enumerate(executive_lines, start=14):
            ws.merge_cells(start_row=offset, start_column=1, end_row=offset, end_column=12)
            ws.cell(offset, 1).value = line
            ws.cell(offset, 1).alignment = Alignment(wrap_text=True)
            ws.cell(offset, 1).font = Font(size=10)

        # Base dos gráficos (colunas ocultas).
        start = 2
        ws["N1"] = "Linha"
        ws["O1"] = f"Faturamento {period_days}d"
        ws["Q1"] = "Linha"
        ws["R1"] = "Valor Estoque"
        ws["S1"] = "Valor Alto/Excesso"
        for i, row in summary.iterrows():
            excel_row = start + i
            ws.cell(excel_row, 14).value = row["linha"]
            ws.cell(excel_row, 15).value = float(row[revenue_col])
            ws.cell(excel_row, 17).value = row["linha"]
            ws.cell(excel_row, 18).value = float(row["valor_estoque"])
            ws.cell(excel_row, 19).value = float(row["valor_alto_excesso"])

        status_counts = products["status"].value_counts()
        ws["U1"] = "Status"
        ws["V1"] = "Itens"
        for i, (status, qty) in enumerate(status_counts.items(), start=2):
            ws.cell(i, 21).value = status
            ws.cell(i, 22).value = int(qty)

        max_line_row = 1 + len(summary)
        chart1 = BarChart()
        chart1.type = "bar"
        chart1.style = 10
        chart1.title = f"Faturamento por Linha — {period_days} dias"
        chart1.x_axis.title = "R$"
        chart1.y_axis.title = "Linha"
        chart1.legend = None
        chart1.height = 8
        chart1.width = 14
        chart1.add_data(Reference(ws, min_col=15, min_row=1, max_row=max_line_row), titles_from_data=True)
        chart1.set_categories(Reference(ws, min_col=14, min_row=2, max_row=max_line_row))
        ws.add_chart(chart1, "A19")

        chart2 = BarChart()
        chart2.type = "bar"
        chart2.style = 11
        chart2.title = "Valor de Estoque x Alto/Excesso"
        chart2.x_axis.title = "R$"
        chart2.y_axis.title = "Linha"
        chart2.height = 8
        chart2.width = 14
        chart2.add_data(
            Reference(ws, min_col=18, max_col=19, min_row=1, max_row=max_line_row),
            titles_from_data=True,
        )
        chart2.set_categories(Reference(ws, min_col=17, min_row=2, max_row=max_line_row))
        ws.add_chart(chart2, "G19")

        status_last = 1 + len(status_counts)
        chart3 = DoughnutChart()
        chart3.style = 10
        chart3.title = "Distribuição dos SKUs por Status"
        chart3.holeSize = 55
        chart3.height = 8
        chart3.width = 13
        chart3.add_data(
            Reference(ws, min_col=22, min_row=1, max_row=status_last),
            titles_from_data=True,
        )
        chart3.set_categories(Reference(ws, min_col=21, min_row=2, max_row=status_last))
        chart3.dataLabels = DataLabelList()
        chart3.dataLabels.showPercent = True
        chart3.dataLabels.showLeaderLines = True
        ws.add_chart(chart3, "A35")

        ws.merge_cells("G35:L35")
        ws["G35"] = "COMO LER O RELATÓRIO"
        ws["G35"].fill = PatternFill("solid", fgColor=NAVY)
        ws["G35"].font = Font(color=WHITE, bold=True)
        guide = [
            ("A36", "PERIGOSO", "Cobertura muito baixa; atenção imediata."),
            ("A37", "ABAIXO", "Abaixo da faixa recomendada."),
            ("A38", "OK", "Estoque dentro da faixa esperada."),
            ("A39", "ALTO / EXCESSO", "Capital acima da faixa de cobertura."),
            ("A40", "PARADO", "Saldo positivo sem venda no período."),
        ]
        for row_num, (label, desc) in enumerate(
            [(x[1], x[2]) for x in guide], start=36
        ):
            ws.merge_cells(start_row=row_num, start_column=7, end_row=row_num, end_column=8)
            ws.merge_cells(start_row=row_num, start_column=9, end_row=row_num, end_column=12)
            ws.cell(row_num, 7).value = label
            ws.cell(row_num, 7).font = Font(bold=True)
            ws.cell(row_num, 9).value = desc

        for col in range(14, 23):
            ws.column_dimensions[get_column_letter(col)].hidden = True

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

        # Escala visual na tabela gerencial.
        resumo_ws = wb["RESUMO LINHAS"]
        header_map = {
            resumo_ws.cell(4, c).value: c
            for c in range(1, resumo_ws.max_column + 1)
        }
        if "Valor Alto/Excesso" in header_map:
            col = get_column_letter(header_map["Valor Alto/Excesso"])
            resumo_ws[f"{col}5:{col}{resumo_ws.max_row}"].conditional_formatting.add(
                ColorScaleRule(
                    start_type="min",
                    start_color="E2F0D9",
                    mid_type="percentile",
                    mid_value=50,
                    mid_color="FFF2CC",
                    end_type="max",
                    end_color="F4CCCC",
                )
            )

    return output.getvalue()


def render_analise_linha():
    st.title("📊 Análise Gerencial de Linha")
    st.caption(
        "Painel executivo com faturamento, estoque, Curva ABC, cobertura, excesso "
        "e produtos parados — direto do relatório bruto do sistema."
    )

    uploaded = st.file_uploader(
        "Importe o relatório bruto por marca",
        type=["xlsx", "xls", "csv"],
        key="linha_raw_v2",
        help="Use o arquivo exatamente como ele sai do sistema.",
    )
    if not uploaded:
        st.info("Envie o relatório bruto para montar o dashboard gerencial.")
        return

    try:
        raw = read_file(uploaded)
        base, long_days = standardize_line_report(raw)
    except Exception as exc:
        st.error(str(exc))
        return

    a1, a2 = st.columns([2, 1])
    analysis_name = a1.text_input(
        "Nome da análise / marca",
        value=uploaded.name.rsplit(".", 1)[0],
        key="nome_analise_linha_v2",
    )
    period_label = a2.radio(
        "Período principal",
        ["90 dias", f"{long_days} dias"],
        horizontal=True,
        key="periodo_linha_v2",
    )
    period_days = 90 if period_label == "90 dias" else long_days

    products, summary = build_line_analysis(base, period_days)
    revenue_col = "faturamento_90" if period_days == 90 else "faturamento_longo"

    total_revenue = float(products["faturamento_periodo"].sum())
    total_stock = float(products["estoque"].sum())
    stock_value = float(products["valor_estoque"].sum())
    high_mask = products["status"].isin(["ALTO", "EXCESSO"])
    stopped_mask = products["status"].eq("SEM VENDA - ESTOQUE PARADO")
    dangerous_mask = products["status"].eq("PERIGOSO")
    excess_value = float(products.loc[high_mask, "valor_estoque"].sum())
    stopped_value = float(products.loc[stopped_mask, "valor_estoque"].sum())
    problem_share = (
        (excess_value + stopped_value) / stock_value
        if stock_value
        else 0
    )

    st.markdown("### Visão executiva")
    cols = st.columns(4)
    cols[0].markdown(_card_html("SKUs analisados", integer(len(products)), f"{products['linha'].nunique()} linhas"), unsafe_allow_html=True)
    cols[1].markdown(_card_html(f"Faturamento {period_days}d", brl(total_revenue), "valor estimado por preço de venda"), unsafe_allow_html=True)
    cols[2].markdown(_card_html("Valor do estoque", brl(stock_value), f"{integer(total_stock)} unidades"), unsafe_allow_html=True)
    cols[3].markdown(_card_html("Estoque em atenção", f"{problem_share:.1%}", "Alto/Excesso + parado"), unsafe_allow_html=True)

    cols2 = st.columns(4)
    cols2[0].markdown(_card_html("Itens perigosos", integer(dangerous_mask.sum()), "cobertura muito baixa"), unsafe_allow_html=True)
    cols2[1].markdown(_card_html("Itens Alto/Excesso", integer(high_mask.sum()), brl(excess_value)), unsafe_allow_html=True)
    cols2[2].markdown(_card_html("Itens parados", integer(stopped_mask.sum()), brl(stopped_value)), unsafe_allow_html=True)
    cols2[3].markdown(_card_html("Curva A", integer((products['curva_abc'] == 'A').sum()), "itens de maior peso no faturamento"), unsafe_allow_html=True)

    if not summary.empty:
        best_sales = summary.loc[summary[revenue_col].idxmax()]
        biggest_excess = summary.loc[summary["valor_alto_excesso"].idxmax()]
        biggest_stock = summary.loc[summary["valor_estoque"].idxmax()]
        share = float(best_sales[revenue_col]) / total_revenue if total_revenue else 0

        st.markdown("### Resumo executivo")
        st.info(
            f"**{best_sales['linha']}** lidera o faturamento com **{share:.1%}** do total. "
            f"O maior valor concentrado em itens Alto/Excesso está em **{biggest_excess['linha']}** "
            f"({brl(biggest_excess['valor_alto_excesso'])}). "
            f"A maior concentração de estoque está em **{biggest_stock['linha']}** "
            f"({brl(biggest_stock['valor_estoque'])})."
        )

    st.markdown("### Gráficos gerenciais")
    g1, g2 = st.columns(2)

    revenue_chart = (
        summary[["linha", revenue_col]]
        .set_index("linha")
        .rename(columns={revenue_col: f"Faturamento {period_days}d"})
    )
    with g1:
        st.markdown("**Faturamento por linha**")
        st.bar_chart(revenue_chart, use_container_width=True)

    stock_chart = (
        summary[["linha", "valor_estoque", "valor_alto_excesso"]]
        .set_index("linha")
        .rename(
            columns={
                "valor_estoque": "Valor estoque",
                "valor_alto_excesso": "Alto/Excesso",
            }
        )
    )
    with g2:
        st.markdown("**Estoque x Alto/Excesso por linha**")
        st.bar_chart(stock_chart, use_container_width=True)

    g3, g4 = st.columns(2)
    status_chart = products["status"].value_counts().rename("Itens").to_frame()
    with g3:
        st.markdown("**Distribuição dos produtos por status**")
        st.bar_chart(status_chart, use_container_width=True)

    abc_chart = products["curva_abc"].value_counts().reindex(["A", "B", "C"], fill_value=0).rename("Itens").to_frame()
    with g4:
        st.markdown("**Distribuição Curva ABC**")
        st.bar_chart(abc_chart, use_container_width=True)

    st.markdown("### Ranking gerencial por linha")
    manager = _friendly_summary(summary, long_days)[
        [
            "Linha",
            "SKUs",
            "Faturamento 90d",
            f"Faturamento {long_days}d",
            "Estoque (un.)",
            "Valor Estoque",
            "Valor Alto/Excesso",
            "Valor Parado",
            "Perigoso",
            "Abaixo Recomend.",
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
            f"Faturamento {long_days}d": st.column_config.NumberColumn(format="R$ %.2f"),
            "Valor Estoque": st.column_config.NumberColumn(format="R$ %.2f"),
            "Valor Alto/Excesso": st.column_config.NumberColumn(format="R$ %.2f"),
            "Valor Parado": st.column_config.NumberColumn(format="R$ %.2f"),
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
            ["Perigoso / Abaixo", "Alto / Excesso", "Estoque parado"],
            horizontal=True,
            key="criticos_v2",
        )
        if crit_kind == "Perigoso / Abaixo":
            filtered = products_filtered[
                products_filtered["status"].isin(["PERIGOSO", "ABAIXO DO RECOMENDADO"])
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
        st.markdown(
            "**Curva ABC:** A até 80% do faturamento acumulado; B de 80% a 95%; "
            "C acima de 95%.\n\n"
            "**Curva A:** <30 dias Perigoso; 30–<90 Abaixo; 90–180 OK; >180 Excesso.\n\n"
            "**Curva B:** <30 Perigoso; 30–<90 Abaixo; 90–120 OK; >120–150 Alto; >150 Excesso.\n\n"
            "**Curva C:** <30 Perigoso; 30–<90 Abaixo; 90–120 OK; >120 Excesso.\n\n"
            "Produto sem venda e com saldo positivo é classificado como **Estoque parado**."
        )

    export = formatted_xlsx_bytes(
        summary=summary,
        products=products,
        raw=raw,
        period_days=period_days,
        long_days=long_days,
        analysis_name=analysis_name,
    )

    st.download_button(
        "📊 Baixar relatório gerencial formatado (.xlsx)",
        data=export,
        file_name=f"analise_gerencial_linha_{period_days}d.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        key="download_analise_gerencial_v2",
    )

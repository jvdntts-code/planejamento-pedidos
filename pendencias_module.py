import io
import re
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


NAVY = "17365D"
WHITE = "FFFFFF"
LIGHT_GREEN = "E2F0D9"
LIGHT_YELLOW = "FFF2CC"
LIGHT_RED = "F4CCCC"
LIGHT_ORANGE = "FCE4D6"

STATUS_ORDER = [
    "QUANTIDADE DIVERGENTE",
    "SÓ NO FORNECEDOR",
    "SÓ NO SISTEMA",
    "OK",
]

STATUS_FILL = {
    "QUANTIDADE DIVERGENTE": LIGHT_YELLOW,
    "SÓ NO FORNECEDOR": LIGHT_ORANGE,
    "SÓ NO SISTEMA": LIGHT_RED,
    "OK": LIGHT_GREEN,
}


def norm(value):
    value = str(value).strip().lower()
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "", value)


def normalize_reference(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"\.0$", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def find_col(df, *names):
    mapping = {norm(c): c for c in df.columns}
    for name in names:
        key = norm(name)
        if key in mapping:
            return mapping[key]
    return None


def read_single_table(uploaded):
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


def read_combined_workbook(uploaded):
    raw = uploaded.getvalue()
    book = pd.read_excel(io.BytesIO(raw), sheet_name=None)
    if not book:
        raise ValueError("O arquivo não possui abas legíveis.")

    supplier_sheet = None
    system_sheet = None
    for sheet_name in book:
        key = norm(sheet_name)
        if supplier_sheet is None and "fornecedor" in key:
            supplier_sheet = sheet_name
        if system_sheet is None and "sistema" in key:
            system_sheet = sheet_name

    if supplier_sheet is None or system_sheet is None:
        raise ValueError(
            "Não encontrei as duas abas esperadas. O arquivo deve ter uma aba do FORNECEDOR e outra do SISTEMA."
        )

    return book[system_sheet], book[supplier_sheet], system_sheet, supplier_sheet


def prepare_pending(df, source):
    if df is None or df.empty:
        raise ValueError(f"A base de {source.lower()} está vazia.")

    ref_col = find_col(
        df,
        "REFERENCIA",
        "REFERÊNCIA",
        "NumFabricante",
        "Numero Fabricante",
        "Referência Fabricante",
        "Codigo Fabricante",
    )

    if source == "SISTEMA":
        qty_col = find_col(
            df,
            "SOMA PENDENTE",
            "QTD PENDENTE",
            "PENDENCIA",
            "PENDÊNCIA",
            "QUANTIDADE PENDENTE",
            "QUANTIDADE",
            "QTD",
        )
    else:
        qty_col = find_col(
            df,
            "SOMA PENDENTE FORNECEDOR",
            "QTD PENDENTE FORNECEDOR",
            "PENDENCIA FORNECEDOR",
            "PENDÊNCIA FORNECEDOR",
            "QUANTIDADE PENDENTE",
            "QUANTIDADE",
            "QTD PENDENTE",
            "QTD",
        )

    if ref_col is None or qty_col is None:
        expected = (
            "REFERENCIA + SOMA PENDENTE"
            if source == "SISTEMA"
            else "REFERENCIA + SOMA PENDENTE FORNECEDOR"
        )
        raise ValueError(
            f"Não consegui identificar as colunas da base {source}. Esperado: {expected}."
        )

    out = pd.DataFrame()
    out["REFERENCIA"] = df[ref_col].map(normalize_reference)
    out["QUANTIDADE"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    out = out[out["REFERENCIA"].ne("")].copy()
    out = out.groupby("REFERENCIA", as_index=False)["QUANTIDADE"].sum()
    return out


def compare_pending(system_df, supplier_df):
    system = prepare_pending(system_df, "SISTEMA").rename(
        columns={"QUANTIDADE": "QTD SISTEMA"}
    )
    supplier = prepare_pending(supplier_df, "FORNECEDOR").rename(
        columns={"QUANTIDADE": "QTD FORNECEDOR"}
    )

    system["TEM NO SISTEMA"] = True
    supplier["TEM NO FORNECEDOR"] = True

    result = system.merge(supplier, on="REFERENCIA", how="outer")
    result["TEM NO SISTEMA"] = result["TEM NO SISTEMA"].fillna(False).astype(bool)
    result["TEM NO FORNECEDOR"] = result["TEM NO FORNECEDOR"].fillna(False).astype(bool)
    result["QTD SISTEMA"] = pd.to_numeric(result["QTD SISTEMA"], errors="coerce").fillna(0)
    result["QTD FORNECEDOR"] = pd.to_numeric(result["QTD FORNECEDOR"], errors="coerce").fillna(0)
    result["DIFERENÇA FORNECEDOR - SISTEMA"] = result["QTD FORNECEDOR"] - result["QTD SISTEMA"]

    conditions = [
        (~result["TEM NO SISTEMA"]) & result["TEM NO FORNECEDOR"],
        result["TEM NO SISTEMA"] & (~result["TEM NO FORNECEDOR"]),
        result["TEM NO SISTEMA"]
        & result["TEM NO FORNECEDOR"]
        & (~np.isclose(result["QTD SISTEMA"], result["QTD FORNECEDOR"])),
    ]
    choices = [
        "SÓ NO FORNECEDOR",
        "SÓ NO SISTEMA",
        "QUANTIDADE DIVERGENTE",
    ]
    result["STATUS"] = np.select(conditions, choices, default="OK")

    def reading(row):
        if row["STATUS"] == "SÓ NO FORNECEDOR":
            return "Fornecedor possui pendência que não aparece no sistema"
        if row["STATUS"] == "SÓ NO SISTEMA":
            return "Sistema possui pendência que não aparece no fornecedor"
        if row["STATUS"] == "QUANTIDADE DIVERGENTE":
            diff = row["DIFERENÇA FORNECEDOR - SISTEMA"]
            if diff > 0:
                return f"Fornecedor possui {abs(diff):g} unidade(s) a mais"
            return f"Sistema possui {abs(diff):g} unidade(s) a mais"
        return "Quantidades conferem"

    result["LEITURA"] = result.apply(reading, axis=1)

    order_map = {name: idx for idx, name in enumerate(STATUS_ORDER)}
    result["_ORDEM"] = result["STATUS"].map(order_map).fillna(99)
    result = result.sort_values(["_ORDEM", "REFERENCIA"], kind="stable").drop(columns="_ORDEM")
    return result.reset_index(drop=True)


def pending_template_bytes():
    supplier = pd.DataFrame(columns=["REFERENCIA", "SOMA PENDENTE FORNECEDOR"])
    system = pd.DataFrame(columns=["REFERENCIA", "SOMA PENDENTE"])
    example_supplier = pd.DataFrame({
        "REFERENCIA": ["REF001", "REF002", "REF004"],
        "SOMA PENDENTE FORNECEDOR": [10, 5, 8],
    })
    example_system = pd.DataFrame({
        "REFERENCIA": ["REF001", "REF002", "REF003"],
        "SOMA PENDENTE": [10, 7, 12],
    })
    instructions = pd.DataFrame([
        {"Etapa": 1, "Orientação": "O arquivo pode conter as duas abas: PENDENCIA FORNECEDOR SOMA e PENDENCIA SISTEMA SOMA."},
        {"Etapa": 2, "Orientação": "Use REFERENCIA como chave de comparação entre o sistema e o fornecedor."},
        {"Etapa": 3, "Orientação": "Na aba do fornecedor, informe a quantidade em SOMA PENDENTE FORNECEDOR."},
        {"Etapa": 4, "Orientação": "Na aba do sistema, informe a quantidade em SOMA PENDENTE."},
        {"Etapa": 5, "Orientação": "Pode haver referências repetidas; o NEXO soma automaticamente antes de comparar."},
        {"Etapa": 6, "Orientação": "O NEXO identifica: quantidade divergente, só no fornecedor, só no sistema e OK."},
    ])

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        supplier.to_excel(writer, sheet_name="PENDENCIA FORNECEDOR SOMA", index=False)
        system.to_excel(writer, sheet_name="PENDENCIA SISTEMA SOMA", index=False)
        instructions.to_excel(writer, sheet_name="INSTRUCOES", index=False)
        example_supplier.to_excel(writer, sheet_name="EXEMPLO FORNECEDOR", index=False)
        example_system.to_excel(writer, sheet_name="EXEMPLO SISTEMA", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.sheet_view.showGridLines = False
            ws.auto_filter.ref = ws.dimensions
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
                max_len = max([len(str(cell.value or "")) for cell in col[:200]] + [10])
                ws.column_dimensions[letter].width = min(max(max_len + 2, 14), 46)
    out.seek(0)
    return out.getvalue()


def comparison_xlsx_bytes(result, system_base, supplier_base):
    summary = (
        result.groupby("STATUS", as_index=False)
        .agg(
            REFERENCIAS=("REFERENCIA", "count"),
            QTD_SISTEMA=("QTD SISTEMA", "sum"),
            QTD_FORNECEDOR=("QTD FORNECEDOR", "sum"),
        )
    )
    summary["DIFERENÇA"] = summary["QTD_FORNECEDOR"] - summary["QTD_SISTEMA"]
    summary["_ORDEM"] = summary["STATUS"].map({s: i for i, s in enumerate(STATUS_ORDER)}).fillna(99)
    summary = summary.sort_values("_ORDEM").drop(columns="_ORDEM")

    divergences = result[result["STATUS"].ne("OK")].copy()

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="RESUMO", index=False)
        divergences.to_excel(writer, sheet_name="DIVERGENCIAS", index=False)
        result.to_excel(writer, sheet_name="TODOS", index=False)
        system_base.to_excel(writer, sheet_name="BASE SISTEMA", index=False)
        supplier_base.to_excel(writer, sheet_name="BASE FORNECEDOR", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.sheet_view.showGridLines = False
            ws.auto_filter.ref = ws.dimensions
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
                max_len = max([len(str(cell.value or "")) for cell in col[:400]] + [10])
                ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 48)

            status_col = None
            for cell in ws[1]:
                if str(cell.value).strip().upper() == "STATUS":
                    status_col = cell.column
                    break
            if status_col:
                for row_idx in range(2, ws.max_row + 1):
                    cell = ws.cell(row=row_idx, column=status_col)
                    fill = STATUS_FILL.get(str(cell.value), None)
                    if fill:
                        cell.fill = PatternFill("solid", fgColor=fill)
                        cell.font = Font(name="Times New Roman", bold=True)

    out.seek(0)
    return out.getvalue()


def render_pendencias():
    st.title("Confronto de Pendências")
    st.caption(
        "Compare a carteira pendente do seu sistema com a carteira do fornecedor e identifique automaticamente todas as divergências."
    )

    with st.expander("O que o NEXO vai conferir", expanded=False):
        st.markdown(
            """
            O confronto usa a **REFERÊNCIA** do produto e classifica cada item em quatro situações:

            - **QUANTIDADE DIVERGENTE** — aparece nos dois, mas com quantidades diferentes;
            - **SÓ NO FORNECEDOR** — existe na carteira do fornecedor, mas não no seu sistema;
            - **SÓ NO SISTEMA** — existe no seu sistema, mas não na carteira do fornecedor;
            - **OK** — aparece nos dois e a quantidade confere.

            Referências repetidas são somadas antes da comparação.
            """
        )

    mode = st.radio(
        "Como deseja importar?",
        ["Arquivo único com duas abas", "Dois arquivos separados"],
        horizontal=True,
        key="pending_import_mode",
    )

    col_upload, col_model = st.columns([2.2, 1])
    with col_model:
        st.markdown("**Primeira vez usando?**")
        st.download_button(
            "Baixar modelo de pendências",
            data=pending_template_bytes(),
            file_name="NEXO_modelo_confronto_pendencias.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="pending_model_download",
        )

    system_df = None
    supplier_df = None

    try:
        with col_upload:
            if mode == "Arquivo único com duas abas":
                combined = st.file_uploader(
                    "Importe o arquivo com as pendências do SISTEMA e do FORNECEDOR",
                    type=["xlsx", "xls"],
                    key="pending_combined_file",
                    help="O NEXO procura automaticamente uma aba com 'FORNECEDOR' e outra com 'SISTEMA' no nome.",
                )
                if combined:
                    system_df, supplier_df, system_sheet, supplier_sheet = read_combined_workbook(combined)
                    st.success(
                        f"Abas reconhecidas: Sistema = {system_sheet} | Fornecedor = {supplier_sheet}"
                    )
            else:
                system_file = st.file_uploader(
                    "1) Pendências do seu SISTEMA",
                    type=["xlsx", "xls", "csv"],
                    key="pending_system_file",
                )
                supplier_file = st.file_uploader(
                    "2) Pendências do FORNECEDOR",
                    type=["xlsx", "xls", "csv"],
                    key="pending_supplier_file",
                )
                if system_file and supplier_file:
                    system_df = read_single_table(system_file)
                    supplier_df = read_single_table(supplier_file)
    except Exception as exc:
        st.error(str(exc))
        return

    if system_df is None or supplier_df is None:
        st.info("Importe as duas bases para iniciar o confronto.")
        return

    try:
        result = compare_pending(system_df, supplier_df)
        system_base = prepare_pending(system_df, "SISTEMA").rename(columns={"QUANTIDADE": "QTD SISTEMA"})
        supplier_base = prepare_pending(supplier_df, "FORNECEDOR").rename(columns={"QUANTIDADE": "QTD FORNECEDOR"})
    except Exception as exc:
        st.error(str(exc))
        return

    total = len(result)
    ok_count = int((result["STATUS"] == "OK").sum())
    qty_diff_count = int((result["STATUS"] == "QUANTIDADE DIVERGENTE").sum())
    supplier_only_count = int((result["STATUS"] == "SÓ NO FORNECEDOR").sum())
    system_only_count = int((result["STATUS"] == "SÓ NO SISTEMA").sum())
    divergent_count = total - ok_count

    st.markdown("### Resumo do confronto")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Referências", f"{total:,}".replace(",", "."))
    c2.metric("Divergências", f"{divergent_count:,}".replace(",", "."))
    c3.metric("Qtd. diferente", f"{qty_diff_count:,}".replace(",", "."))
    c4.metric("Só fornecedor", f"{supplier_only_count:,}".replace(",", "."))
    c5.metric("Só sistema", f"{system_only_count:,}".replace(",", "."))

    q1, q2, q3 = st.columns(3)
    q1.metric("Quantidade total no sistema", f"{result['QTD SISTEMA'].sum():,.0f}".replace(",", "."))
    q2.metric("Quantidade total no fornecedor", f"{result['QTD FORNECEDOR'].sum():,.0f}".replace(",", "."))
    q3.metric("Itens OK", f"{ok_count:,}".replace(",", "."))

    tab_div, tab_all, tab_summary = st.tabs(["Divergências", "Todos os itens", "Resumo"])

    with tab_div:
        statuses = ["QUANTIDADE DIVERGENTE", "SÓ NO FORNECEDOR", "SÓ NO SISTEMA"]
        f1, f2 = st.columns([2, 1])
        selected = f1.multiselect(
            "Filtrar situação",
            options=statuses,
            default=statuses,
            key="pending_status_filter",
        )
        search = f2.text_input("Buscar referência", key="pending_search_ref").strip().upper()

        view = result[result["STATUS"].isin(selected)].copy()
        if search:
            view = view[view["REFERENCIA"].str.contains(search, case=False, na=False)]

        st.dataframe(
            view[[
                "REFERENCIA",
                "QTD SISTEMA",
                "QTD FORNECEDOR",
                "DIFERENÇA FORNECEDOR - SISTEMA",
                "STATUS",
                "LEITURA",
            ]],
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Diferença = quantidade do fornecedor − quantidade do sistema. Valor positivo significa que o fornecedor tem mais; negativo significa que o sistema tem mais."
        )

    with tab_all:
        st.dataframe(
            result[[
                "REFERENCIA",
                "QTD SISTEMA",
                "QTD FORNECEDOR",
                "DIFERENÇA FORNECEDOR - SISTEMA",
                "STATUS",
                "LEITURA",
            ]],
            use_container_width=True,
            hide_index=True,
        )

    with tab_summary:
        summary = (
            result.groupby("STATUS", as_index=False)
            .agg(
                REFERENCIAS=("REFERENCIA", "count"),
                QTD_SISTEMA=("QTD SISTEMA", "sum"),
                QTD_FORNECEDOR=("QTD FORNECEDOR", "sum"),
            )
        )
        summary["DIFERENÇA"] = summary["QTD_FORNECEDOR"] - summary["QTD_SISTEMA"]
        summary["_ORDEM"] = summary["STATUS"].map({s: i for i, s in enumerate(STATUS_ORDER)}).fillna(99)
        summary = summary.sort_values("_ORDEM").drop(columns="_ORDEM")
        st.dataframe(summary, use_container_width=True, hide_index=True)

    st.markdown("### Exportar resultado")
    st.download_button(
        "Baixar confronto completo em Excel",
        data=comparison_xlsx_bytes(result, system_base, supplier_base),
        file_name="NEXO_confronto_pendencias.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="pending_export_xlsx",
    )
    st.caption(
        "O Excel exportado contém RESUMO, DIVERGENCIAS, TODOS, BASE SISTEMA e BASE FORNECEDOR."
    )


# NEXO_PENDING_ANALYSIS_V1
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from auth_module import user_storage_prefix

PENDING_CRITICAL_DAYS = 180
PENDING_DEFAULT_GRACE = 30
PENDING_DATA_BRANCH = "main"
PENDING_MANAGEMENT = {
    "PENDÊNCIA",
    "PENDÊNCIA CRÍTICA",
    "AJUSTAR NO SISTEMA",
    "AJUSTE CRÍTICO",
}
PENDING_ADJUST = {"AJUSTAR NO SISTEMA", "AJUSTE CRÍTICO"}


def _pending_secret(name, default=""):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def _pending_settings():
    repo = str(_pending_secret("GITHUB_DATA_REPO", "")).strip()
    branch = str(
        _pending_secret(
            "GITHUB_DATA_BRANCH",
            _pending_secret("GITHUB_BRANCH", PENDING_DATA_BRANCH),
        )
    ).strip() or PENDING_DATA_BRANCH
    token = str(_pending_secret("GITHUB_TOKEN", "")).strip()
    return repo, branch, token


def _pending_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "nexo-pendencias",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _pending_preferences_path():
    return f"{user_storage_prefix()}/preferences/pending_analysis.json"


def _pending_read_preferences():
    defaults = {
        "carencia_dias": PENDING_DEFAULT_GRACE,
        "desconsiderar_mes_vigente": True,
        "marcas_sem_pendencia": [],
    }
    repo, branch, token = _pending_settings()
    if not repo or not token:
        return defaults, None, None

    path = urllib.parse.quote(_pending_preferences_path(), safe="/")
    ref = urllib.parse.quote(branch, safe="")
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    req = urllib.request.Request(url, headers=_pending_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = base64.b64decode(payload.get("content", "")).decode("utf-8")
        saved = json.loads(raw)
        if isinstance(saved, dict):
            defaults.update(saved)
        defaults["marcas_sem_pendencia"] = sorted({
            str(x).strip().upper()
            for x in defaults.get("marcas_sem_pendencia", [])
            if str(x).strip()
        })
        return defaults, payload.get("sha"), None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return defaults, None, None
        return defaults, None, f"Não foi possível carregar as preferências (HTTP {exc.code})."
    except Exception as exc:
        return defaults, None, f"Não foi possível carregar as preferências: {exc}"


def _pending_write_preferences(data, sha=None):
    repo, branch, token = _pending_settings()
    if not repo or not token:
        return False, "Não foi possível salvar a configuração permanente."

    if sha is None:
        _, sha, error = _pending_read_preferences()
        if error:
            return False, error

    path = urllib.parse.quote(_pending_preferences_path(), safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    payload = {
        "message": "Atualiza preferências de pendências",
        "content": base64.b64encode(raw).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**_pending_headers(token), "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            response.read()
        return True, None
    except Exception as exc:
        return False, f"Não foi possível salvar a configuração: {exc}"


def _pending_clean_id(value):
    if pd.isna(value):
        return ""
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return re.sub(r"\.0$", "", str(value).strip())


def _pending_dates(series):
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    numeric = pd.to_numeric(series, errors="coerce")
    excel = numeric.between(20000, 80000, inclusive="both")
    if excel.any():
        result.loc[excel] = pd.to_datetime(
            numeric.loc[excel],
            unit="D",
            origin="1899-12-30",
            errors="coerce",
        )
    other = ~excel
    if other.any():
        result.loc[other] = pd.to_datetime(
            series.loc[other],
            errors="coerce",
            dayfirst=True,
        )
    return result.dt.normalize()


def _pending_prepare(df):
    if df is None or df.empty:
        raise ValueError("A relação de pendências está vazia.")

    cols = {
        "pedido": find_col(df, "CodPedido", "Pedido", "Codigo Pedido"),
        "codigo": find_col(df, "CodProduto", "Codigo Produto", "Produto"),
        "descricao": find_col(df, "Descricao", "Descrição", "Descicao"),
        "referencia": find_col(df, "NumFabricante", "Referencia", "Referência"),
        "marca": find_col(df, "Nome", "Marca", "Fornecedor", "Fabricante"),
        "pedida": find_col(df, "QuantPedida", "Quantidade Pedida", "Qtd Pedida"),
        "atendida": find_col(df, "QuantAtendida", "Quantidade Atendida", "Qtd Atendida"),
        "pendente": find_col(df, "Pendente", "Quantidade Pendente", "Qtd Pendente"),
        "data": find_col(df, "Data_Pedido_Compra", "Data Pedido Compra", "Data Pedido", "Data"),
    }
    required = ["pedido", "codigo", "marca", "pedida", "atendida", "data"]
    missing = [name for name in required if cols[name] is None]
    if missing:
        raise ValueError(
            "Não consegui reconhecer todas as colunas necessárias da relação bruta."
        )

    out = pd.DataFrame(index=df.index)
    out["PEDIDO"] = df[cols["pedido"]].map(_pending_clean_id)
    out["CODIGO"] = df[cols["codigo"]].map(_pending_clean_id)
    out["DESCRICAO"] = (
        df[cols["descricao"]].fillna("").astype(str).str.strip()
        if cols["descricao"] else ""
    )
    out["REFERENCIA"] = (
        df[cols["referencia"]].map(_pending_clean_id).str.upper()
        if cols["referencia"] else ""
    )
    out["MARCA"] = (
        df[cols["marca"]].fillna("SEM MARCA").astype(str).str.strip()
        .replace("", "SEM MARCA").str.upper()
    )
    out["QTD_PEDIDA"] = pd.to_numeric(df[cols["pedida"]], errors="coerce").fillna(0)
    out["QTD_ATENDIDA"] = pd.to_numeric(df[cols["atendida"]], errors="coerce").fillna(0)
    if cols["pendente"]:
        out["PENDENTE"] = pd.to_numeric(df[cols["pendente"]], errors="coerce").fillna(0)
    else:
        out["PENDENTE"] = out["QTD_PEDIDA"] - out["QTD_ATENDIDA"]
    out["DATA_PEDIDO"] = _pending_dates(df[cols["data"]])
    return out.reset_index(drop=True)


def _pending_band(days):
    if pd.isna(days):
        return "SEM DATA"
    days = int(days)
    if days <= 30:
        return "ATÉ 30 DIAS"
    if days <= 60:
        return "31 A 60 DIAS"
    if days <= 90:
        return "61 A 90 DIAS"
    if days <= 180:
        return "91 A 180 DIAS"
    return "ACIMA DE 180 DIAS"


def _pending_classify(df, grace, ignore_month, no_pending_brands):
    today = pd.Timestamp(date.today())
    out = df.copy()
    out["DIAS"] = (today - out["DATA_PEDIDO"]).dt.days
    out["FAIXA"] = out["DIAS"].map(_pending_band)
    out["MES_ATUAL"] = (
        out["DATA_PEDIDO"].dt.year.eq(today.year)
        & out["DATA_PEDIDO"].dt.month.eq(today.month)
    ).fillna(False)
    no_pending = {str(x).strip().upper() for x in no_pending_brands}
    out["NAO_MANTEM"] = out["MARCA"].isin(no_pending)

    def classify(row):
        if pd.isna(row["DATA_PEDIDO"]):
            return "SEM DATA"
        if ignore_month and row["MES_ATUAL"]:
            return "EM ABERTO RECENTE"
        days = int(row["DIAS"])
        if days <= int(grace):
            return "EM ABERTO RECENTE"
        if row["NAO_MANTEM"]:
            return "AJUSTE CRÍTICO" if days > PENDING_CRITICAL_DAYS else "AJUSTAR NO SISTEMA"
        return "PENDÊNCIA CRÍTICA" if days > PENDING_CRITICAL_DAYS else "PENDÊNCIA"

    out["SITUACAO"] = out.apply(classify, axis=1)
    out["GERENCIAL"] = out["SITUACAO"].isin(PENDING_MANAGEMENT)
    out["MES_REF"] = out["DATA_PEDIDO"].dt.strftime("%Y-%m").fillna("")
    return out


def _pending_items(df):
    source = df[df["GERENCIAL"]].copy()
    if source.empty:
        return pd.DataFrame()
    result = (
        source.groupby(
            ["CODIGO", "REFERENCIA", "DESCRICAO", "MARCA"],
            dropna=False,
        )
        .agg(
            **{
                "FREQUÊNCIA PEDIDOS": ("PEDIDO", "nunique"),
                "MESES COM PENDÊNCIA": ("MES_REF", lambda x: x[x.ne("")].nunique()),
                "QTD PEDIDA": ("QTD_PEDIDA", "sum"),
                "QTD ATENDIDA": ("QTD_ATENDIDA", "sum"),
                "PENDÊNCIA TOTAL": ("PENDENTE", "sum"),
                "DIAS MAIS ANTIGA": ("DIAS", "max"),
                "MAIS ANTIGA": ("DATA_PEDIDO", "min"),
                "ÚLTIMA OCORRÊNCIA": ("DATA_PEDIDO", "max"),
            }
        )
        .reset_index()
    )
    result["TAXA ATENDIMENTO %"] = np.where(
        result["QTD PEDIDA"] > 0,
        result["QTD ATENDIDA"] / result["QTD PEDIDA"] * 100,
        np.nan,
    )
    return result.sort_values(
        ["FREQUÊNCIA PEDIDOS", "PENDÊNCIA TOTAL", "DIAS MAIS ANTIGA"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def _pending_brands(df):
    source = df[df["GERENCIAL"]].copy()
    if source.empty:
        return pd.DataFrame()
    frequency = (
        source.groupby(["MARCA", "CODIGO"])["PEDIDO"]
        .nunique()
        .reset_index(name="FREQ")
    )
    recurring = (
        frequency[frequency["FREQ"] >= 2]
        .groupby("MARCA")["CODIGO"]
        .nunique()
        .to_dict()
    )
    critical = (
        source[source["DIAS"] > PENDING_CRITICAL_DAYS]
        .groupby("MARCA")["PENDENTE"].sum().to_dict()
    )
    result = (
        source.groupby("MARCA")
        .agg(
            PEDIDOS=("PEDIDO", "nunique"),
            ITENS=("CODIGO", "nunique"),
            **{
                "QTD PEDIDA": ("QTD_PEDIDA", "sum"),
                "QTD ATENDIDA": ("QTD_ATENDIDA", "sum"),
                "PENDÊNCIA TOTAL": ("PENDENTE", "sum"),
                "DIAS MAIS ANTIGA": ("DIAS", "max"),
                "MAIS ANTIGA": ("DATA_PEDIDO", "min"),
                "NÃO MANTÉM PENDÊNCIA": ("NAO_MANTEM", "max"),
            }
        )
        .reset_index()
    )
    result["ITENS RECORRENTES"] = result["MARCA"].map(recurring).fillna(0).astype(int)
    result["PENDÊNCIA >180 DIAS"] = result["MARCA"].map(critical).fillna(0)
    result["TAXA ATENDIMENTO %"] = np.where(
        result["QTD PEDIDA"] > 0,
        result["QTD ATENDIDA"] / result["QTD PEDIDA"] * 100,
        np.nan,
    )
    result["NÃO MANTÉM PENDÊNCIA"] = result["NÃO MANTÉM PENDÊNCIA"].map(
        {True: "SIM", False: "NÃO"}
    )
    return result.sort_values(
        ["PENDÊNCIA TOTAL", "PEDIDOS"],
        ascending=[False, False],
    ).reset_index(drop=True)


def _pending_detail(df):
    return df[[
        "MARCA", "PEDIDO", "DATA_PEDIDO", "DIAS", "SITUACAO",
        "CODIGO", "REFERENCIA", "DESCRICAO",
        "QTD_PEDIDA", "QTD_ATENDIDA", "PENDENTE", "FAIXA",
    ]].copy()


def _pending_display(df):
    out = df.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%d/%m/%Y").fillna("")
    return out


def _pending_export(df, sheet_name):
    out = io.BytesIO()
    safe = re.sub(r"[\\/*?:\[\]]", "", sheet_name)[:31] or "ANALISE"
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=safe, index=False)
        ws = writer.book[safe]
        ws.freeze_panes = "A2"
        ws.sheet_view.showGridLines = False
        ws.auto_filter.ref = ws.dimensions
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
            width = max([len(str(cell.value or "")) for cell in col[:300]] + [10]) + 2
            ws.column_dimensions[letter].width = min(max(width, 12), 42)
    out.seek(0)
    return out.getvalue()


def render_pendencias():
    st.title("Análise de Pendências")
    st.caption(
        "Importe a relação geral e analise frequência, idade, marcas, criticidade e ajustes dentro do NEXO."
    )

    uploaded = st.file_uploader(
        "Relação geral de pendências",
        type=["xlsx", "xls", "csv"],
        key="pending_general_file_v1",
    )
    if not uploaded:
        st.info("Importe a relação bruta de pendências para iniciar a análise.")
        return

    try:
        raw = read_single_table(uploaded)
        base = _pending_prepare(raw)
    except Exception as exc:
        st.error(str(exc))
        return

    positive = base[base["PENDENTE"] > 0].copy()
    negative_count = int((base["PENDENTE"] < 0).sum())
    zero_count = int((base["PENDENTE"] == 0).sum())
    if positive.empty:
        st.warning("Não há quantidades pendentes positivas no arquivo.")
        return

    prefs, prefs_sha, prefs_error = _pending_read_preferences()
    if prefs_error:
        st.warning(prefs_error)

    brands_all = sorted(set(positive["MARCA"]) | set(prefs.get("marcas_sem_pendencia", [])))

    with st.expander("Configuração da análise", expanded=True):
        a, b = st.columns([1, 1.5])
        grace = a.number_input(
            "Considerar pendência após quantos dias?",
            min_value=0,
            max_value=180,
            value=int(prefs.get("carencia_dias", PENDING_DEFAULT_GRACE)),
            key="pending_grace_v1",
        )
        ignore_month = a.checkbox(
            "Desconsiderar pedidos do mês vigente",
            value=bool(prefs.get("desconsiderar_mes_vigente", True)),
            key="pending_ignore_month_v1",
        )
        a.caption("Pendência crítica: acima de 180 dias.")

        no_pending = b.multiselect(
            "Marcas que não mantêm pendência",
            options=brands_all,
            default=[
                x for x in prefs.get("marcas_sem_pendencia", [])
                if x in brands_all
            ],
            key="pending_no_pending_brands_v1",
        )
        b.caption(
            "Depois da carência, essas marcas entram em Ajustar no sistema."
        )
        if b.button(
            "Salvar configuração como padrão",
            use_container_width=True,
            key="pending_save_prefs_v1",
        ):
            ok, error = _pending_write_preferences(
                {
                    "carencia_dias": int(grace),
                    "desconsiderar_mes_vigente": bool(ignore_month),
                    "marcas_sem_pendencia": sorted(set(no_pending)),
                },
                sha=prefs_sha,
            )
            if ok:
                st.success("Configuração salva.")
            else:
                st.error(error)

    analyzed = _pending_classify(positive, grace, ignore_month, no_pending)

    st.markdown("### Filtros")
    f1, f2, f3 = st.columns([1.2, 1.2, 1])
    selected_brands = f1.multiselect(
        "Marcas",
        sorted(analyzed["MARCA"].unique().tolist()),
        key="pending_filter_brands_v1",
    )
    status_options = [
        x for x in [
            "EM ABERTO RECENTE", "PENDÊNCIA", "PENDÊNCIA CRÍTICA",
            "AJUSTAR NO SISTEMA", "AJUSTE CRÍTICO", "SEM DATA",
        ] if x in set(analyzed["SITUACAO"])
    ]
    selected_status = f2.multiselect(
        "Situação",
        status_options,
        default=status_options,
        key="pending_filter_status_v1",
    )
    search = f3.text_input(
        "Buscar",
        placeholder="Pedido, código, referência...",
        key="pending_search_v1",
    ).strip()

    filtered = analyzed.copy()
    if selected_brands:
        filtered = filtered[filtered["MARCA"].isin(selected_brands)]
    filtered = filtered[filtered["SITUACAO"].isin(selected_status)]
    if search:
        term = search.casefold()
        mask = (
            filtered["PEDIDO"].astype(str).str.casefold().str.contains(term, na=False)
            | filtered["CODIGO"].astype(str).str.casefold().str.contains(term, na=False)
            | filtered["REFERENCIA"].astype(str).str.casefold().str.contains(term, na=False)
            | filtered["DESCRICAO"].astype(str).str.casefold().str.contains(term, na=False)
        )
        filtered = filtered[mask]

    management = filtered[filtered["GERENCIAL"]].copy()

    st.markdown("### Visão geral")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Peças em aberto", f"{filtered['PENDENTE'].sum():,.0f}".replace(",", "."))
    k2.metric("Pendência gerencial", f"{management['PENDENTE'].sum():,.0f}".replace(",", "."))
    k3.metric("Pedidos", f"{management['PEDIDO'].nunique():,}".replace(",", "."))
    k4.metric("Itens", f"{management['CODIGO'].nunique():,}".replace(",", "."))
    k5.metric("Marcas", f"{management['MARCA'].nunique():,}".replace(",", "."))
    k6.metric(
        ">180 dias",
        f"{management.loc[management['DIAS'] > 180, 'PENDENTE'].sum():,.0f}".replace(",", "."),
    )
    if negative_count or zero_count:
        st.caption(
            f"Fora da análise principal: {zero_count} linha(s) zerada(s) e {negative_count} negativa(s)."
        )

    age_order = {
        "ATÉ 30 DIAS": 0, "31 A 60 DIAS": 1, "61 A 90 DIAS": 2,
        "91 A 180 DIAS": 3, "ACIMA DE 180 DIAS": 4, "SEM DATA": 5,
    }
    age = (
        filtered.groupby("FAIXA", as_index=False)
        .agg(
            REGISTROS=("PEDIDO", "size"),
            PEDIDOS=("PEDIDO", "nunique"),
            ITENS=("CODIGO", "nunique"),
            PEÇAS=("PENDENTE", "sum"),
        )
    )
    age["_ord"] = age["FAIXA"].map(age_order).fillna(99)
    age = age.sort_values("_ord").drop(columns="_ord")
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("#### Tempo de pendência")
        st.dataframe(age, use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### Peças por faixa")
        if not age.empty:
            st.bar_chart(age.set_index("FAIXA")[["PEÇAS"]], use_container_width=True)

    items = _pending_items(filtered)
    brands = _pending_brands(filtered)
    critical = filtered[
        filtered["GERENCIAL"] & (filtered["DIAS"] > PENDING_CRITICAL_DAYS)
    ].copy()
    adjust = filtered[filtered["SITUACAO"].isin(PENDING_ADJUST)].copy()
    detail = _pending_detail(filtered)

    tabs = st.tabs([
        "Itens recorrentes",
        "Análise por marca",
        "Acima de 180 dias",
        "Ajustar no sistema",
        "Base analisada",
        "Exportar",
    ])

    with tabs[0]:
        st.caption(
            "Frequência = quantidade de pedidos diferentes em que o item permaneceu pendente."
        )
        if items.empty:
            st.info("Nenhum item gerencial nos filtros atuais.")
        else:
            q1, q2, q3 = st.columns([1.2, 1, 1])
            order = q1.selectbox(
                "Ordenar por",
                ["Frequência", "Quantidade pendente", "Mais antiga"],
                key="pending_item_order_v1",
            )
            min_freq = q2.number_input(
                "Frequência mínima",
                min_value=1,
                value=1,
                step=1,
                key="pending_min_freq_v1",
            )
            top = q3.selectbox(
                "Mostrar",
                [20, 50, 100, "Todos"],
                index=1,
                key="pending_top_v1",
            )
            view = items[items["FREQUÊNCIA PEDIDOS"] >= int(min_freq)].copy()
            if order == "Quantidade pendente":
                view = view.sort_values("PENDÊNCIA TOTAL", ascending=False)
            elif order == "Mais antiga":
                view = view.sort_values("DIAS MAIS ANTIGA", ascending=False)
            else:
                view = view.sort_values(
                    ["FREQUÊNCIA PEDIDOS", "PENDÊNCIA TOTAL"],
                    ascending=[False, False],
                )
            if top != "Todos":
                view = view.head(int(top))
            st.dataframe(_pending_display(view), use_container_width=True, hide_index=True)

    with tabs[1]:
        if brands.empty:
            st.info("Nenhuma marca gerencial nos filtros atuais.")
        else:
            st.dataframe(_pending_display(brands), use_container_width=True, hide_index=True)

    with tabs[2]:
        if critical.empty:
            st.success("Nenhuma pendência gerencial acima de 180 dias.")
        else:
            summary = (
                critical.groupby("MARCA", as_index=False)
                .agg(
                    PEDIDOS=("PEDIDO", "nunique"),
                    ITENS=("CODIGO", "nunique"),
                    PEÇAS=("PENDENTE", "sum"),
                    **{"MAIS ANTIGA (DIAS)": ("DIAS", "max")},
                )
                .sort_values(["PEÇAS", "PEDIDOS"], ascending=[False, False])
            )
            st.dataframe(summary, use_container_width=True, hide_index=True)
            st.dataframe(
                _pending_display(_pending_detail(critical).sort_values("DIAS", ascending=False)),
                use_container_width=True,
                hide_index=True,
            )

    with tabs[3]:
        if not no_pending:
            st.info("Cadastre acima as marcas que não mantêm pendência.")
        elif adjust.empty:
            st.success("Nenhum saldo para ajuste com as regras atuais.")
        else:
            summary = (
                adjust.groupby("MARCA", as_index=False)
                .agg(
                    PEDIDOS=("PEDIDO", "nunique"),
                    ITENS=("CODIGO", "nunique"),
                    PEÇAS=("PENDENTE", "sum"),
                    **{"MAIS ANTIGA (DIAS)": ("DIAS", "max")},
                )
                .sort_values(["PEÇAS", "PEDIDOS"], ascending=[False, False])
            )
            st.dataframe(summary, use_container_width=True, hide_index=True)
            st.dataframe(
                _pending_display(_pending_detail(adjust).sort_values("DIAS", ascending=False)),
                use_container_width=True,
                hide_index=True,
            )

    with tabs[4]:
        st.dataframe(
            _pending_display(detail.sort_values("DIAS", ascending=False, na_position="last")),
            use_container_width=True,
            hide_index=True,
        )

    with tabs[5]:
        datasets = {
            "Itens recorrentes": items,
            "Análise por marca": brands,
            "Pendências acima de 180 dias": _pending_detail(critical),
            "Ajustar no sistema": _pending_detail(adjust),
            "Base analisada": detail,
        }
        choice = st.selectbox(
            "O que deseja exportar?",
            list(datasets.keys()),
            key="pending_export_choice_v1",
        )
        export_df = datasets[choice].copy().reset_index(drop=True)
        if export_df.empty:
            st.info("Não há registros nessa visão.")
        else:
            export_all = st.checkbox(
                "Exportar todos os registros desta visão",
                value=True,
                key="pending_export_all_v1",
            )
            selected = export_df
            if not export_all:
                editor = export_df.copy()
                editor.insert(0, "EXPORTAR", False)
                edited = st.data_editor(
                    _pending_display(editor),
                    use_container_width=True,
                    hide_index=True,
                    disabled=[x for x in editor.columns if x != "EXPORTAR"],
                    column_config={
                        "EXPORTAR": st.column_config.CheckboxColumn("Exportar")
                    },
                    key="pending_export_editor_v1",
                )
                positions = edited.index[edited["EXPORTAR"] == True].tolist()
                selected = export_df.iloc[positions].copy()

            columns = st.multiselect(
                "Colunas do arquivo",
                options=list(export_df.columns),
                default=list(export_df.columns),
                key="pending_export_columns_v1",
            )
            if columns and not selected.empty:
                final = selected[columns].copy()
                st.caption(f"{len(final):,} registro(s) selecionado(s).".replace(",", "."))
                st.download_button(
                    "Baixar seleção em Excel",
                    data=_pending_export(final, choice),
                    file_name="NEXO_analise_pendencias.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="pending_download_v1",
                )
            else:
                st.info("Selecione registros e colunas para exportar.")

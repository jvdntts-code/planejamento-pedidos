import io
import math
import re
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st


DEFAULT_LIMITS = {
    "AP": 150,
    "AQ": 150,
    "BP": 150,
    "BQ": 90,
    "CP": 90,
    "CQ": 90,
    "CR": 90,
}

REQUIRED_COLUMNS = [
    "Codigo",
    "Descrição",
    "NumFabricante",
    "Estoque do Grupo",
    "Vendas90diasRoni",
    "Vendas150diasRoni",
]


def _norm(value):
    text = str(value).strip().lower()
    text = "".join(
        c
        for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "", text)


def _find_col(df, *names):
    mapping = {_norm(col): col for col in df.columns}
    for name in names:
        key = _norm(name)
        if key in mapping:
            return mapping[key]
    return None


def _num(series, default=0.0):
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _read_file(uploaded):
    raw = uploaded.getvalue()
    name = uploaded.name.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return pd.read_csv(
                    io.BytesIO(raw),
                    sep=None,
                    engine="python",
                    encoding=enc,
                )
            except Exception:
                pass
    raise ValueError("Arquivo não reconhecido. Use XLSX, XLS ou CSV.")


def _normalize_code(value):
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"\.0$", "", text)
    return re.sub(r"[^A-Z0-9]+", "", text)


def _classify_with_ties(values, cut_first, cut_second, labels):
    values = pd.to_numeric(values, errors="coerce").fillna(0).clip(lower=0)
    total = float(values.sum())
    if total <= 0:
        return pd.Series(labels[-1], index=values.index), pd.Series(1.0, index=values.index)

    totals_by_value = values.groupby(values).sum().sort_index(ascending=False)
    cumulative_by_value = (totals_by_value.cumsum() / total).to_dict()
    accumulated = values.map(cumulative_by_value).fillna(1.0)

    curve = np.select(
        [
            accumulated <= float(cut_first) / 100.0,
            accumulated <= float(cut_second) / 100.0,
        ],
        [labels[0], labels[1]],
        default=labels[2],
    )
    return pd.Series(curve, index=values.index), accumulated


def _standardize_report(df):
    missing = [
        name
        for name in REQUIRED_COLUMNS
        if _find_col(df, name, "Descricao" if name == "Descrição" else name) is None
    ]
    if missing:
        raise ValueError(
            "O relatório não possui todas as colunas obrigatórias: "
            + ", ".join(missing)
        )

    out = pd.DataFrame()
    out["codigo"] = df[_find_col(df, "Codigo")].map(_normalize_code)
    out["descricao"] = (
        df[_find_col(df, "Descrição", "Descricao")]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    out["referencia"] = (
        df[_find_col(df, "NumFabricante")]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    line_code = _find_col(df, "CodLinha")
    line_name = _find_col(df, "Nome")
    out["cod_linha"] = df[line_code] if line_code else ""
    out["linha"] = (
        df[line_name].fillna("").astype(str).str.strip()
        if line_name
        else ""
    )

    out["estoque"] = _num(df[_find_col(df, "Estoque do Grupo")])

    minimum_col = _find_col(df, "estoqueMinGrupo")
    out["minimo"] = _num(df[minimum_col]) if minimum_col else 0.0

    for days in (30, 60, 90, 120, 150, 360, 365):
        col = _find_col(
            df,
            f"Vendas{days}diasRoni",
            f"Vendas{days}dias",
            f"Vendas {days} dias",
        )
        if col is not None:
            out[f"vendas_{days}"] = _num(df[col])

    pending_col = _find_col(
        df,
        "Pendencias",
        "Pendências",
        "Pendencia",
        "Pendência",
        "EmPdCompras",
    )
    out["pendencias"] = _num(df[pending_col]) if pending_col else 0.0

    # Complementos que podem vir no próprio arquivo.
    abc_col = _find_col(df, "Curva ABC", "ABC", "CurvaABC")
    if abc_col is not None:
        out["curva_abc_importada"] = (
            df[abc_col].fillna("").astype(str).str.upper().str.strip()
        )

    value_col = _find_col(
        df,
        "Valor Unitario",
        "Valor Unitário",
        "ValorCompra",
        "Valor Compra",
        "Preco Compra",
        "Preço Compra",
        "Custo Unitario",
        "Custo Unitário",
        "ValorCustoBrutoLista99",
        "Preco Venda",
        "Preço Venda",
    )
    if value_col is not None:
        out["valor_unitario"] = _num(df[value_col])

    out = out[out["codigo"].ne("")].copy()
    return out.reset_index(drop=True)


def _merge_complement(base, complement):
    if complement is None or complement.empty:
        return base

    code_col = _find_col(complement, "Codigo", "Código", "CODIGO INTERNO")
    if code_col is None:
        raise ValueError("O arquivo complementar precisa ter a coluna Codigo.")

    x = pd.DataFrame()
    x["codigo"] = complement[code_col].map(_normalize_code)

    abc_col = _find_col(complement, "Curva ABC", "ABC", "CurvaABC")
    if abc_col is not None:
        x["curva_abc_complemento"] = (
            complement[abc_col].fillna("").astype(str).str.upper().str.strip()
        )

    value_col = _find_col(
        complement,
        "Valor Unitario",
        "Valor Unitário",
        "ValorCompra",
        "Valor Compra",
        "Preco Compra",
        "Preço Compra",
        "Custo Unitario",
        "Custo Unitário",
        "ValorCustoBrutoLista99",
        "Preco Venda",
        "Preço Venda",
    )
    if value_col is not None:
        x["valor_unitario_complemento"] = _num(complement[value_col])

    if len(x.columns) == 1:
        raise ValueError(
            "O arquivo complementar deve ter Curva ABC e/ou Valor Unitário."
        )

    x = x[x["codigo"].ne("")].drop_duplicates("codigo", keep="last")
    return base.merge(x, on="codigo", how="left")


def _xlsx_bytes(result, config):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="SIMULACAO", index=False)
        config.to_excel(writer, sheet_name="CONFIGURACAO", index=False)

        for sheet_name in ("SIMULACAO", "CONFIGURACAO"):
            ws = writer.book[sheet_name]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                letter = col[0].column_letter
                max_len = max(
                    len(str(cell.value or ""))
                    for cell in list(col)[:400]
                )
                ws.column_dimensions[letter].width = min(max(max_len + 2, 11), 34)

    return output.getvalue()


def _allocate_goal(data, mode, target, order_rule):
    result = data.copy()
    result["qtd_sugerida"] = 0

    eligible = result[
        result["capacidade_compra"].gt(0)
        & result["limite_dias"].notna()
    ].copy()

    if mode == "Meta por valor":
        eligible = eligible[eligible["valor_unitario"].gt(0)].copy()

    if order_rule == "Menor cobertura primeiro":
        eligible = eligible.sort_values(
            ["cobertura_projetada_dias", "vendas_90", "capacidade_compra"],
            ascending=[True, False, False],
        )
    elif order_rule == "Maior giro (P → Q → R)":
        eligible["_pqr_rank"] = eligible["curva_pqr"].map(
            {"P": 0, "Q": 1, "R": 2}
        ).fillna(9)
        eligible = eligible.sort_values(
            ["_pqr_rank", "vendas_90", "cobertura_projetada_dias"],
            ascending=[True, False, True],
        )
    else:
        eligible = eligible.sort_values(
            ["capacidade_compra", "vendas_90"],
            ascending=[False, False],
        )

    remaining = float(target)
    suggestions = {}

    for _, row in eligible.iterrows():
        if remaining <= 0:
            break

        capacity = int(max(math.floor(float(row["capacidade_compra"])), 0))
        if capacity <= 0:
            continue

        if mode == "Meta por peças":
            take = min(capacity, int(math.ceil(remaining)))
            remaining -= take
        else:
            unit_value = float(row["valor_unitario"])
            if unit_value <= 0:
                continue
            take = min(capacity, int(math.floor(remaining / unit_value)))
            if take <= 0:
                continue
            remaining -= take * unit_value

        suggestions[row["codigo"]] = suggestions.get(row["codigo"], 0) + int(take)

    result["qtd_sugerida"] = result["codigo"].map(suggestions).fillna(0).astype(int)
    result["valor_sugerido"] = result["qtd_sugerida"] * result["valor_unitario"]
    result["estoque_apos_sugestao"] = (
        result["estoque_projetado"] + result["qtd_sugerida"]
    )
    result["cobertura_apos_sugestao"] = np.where(
        result["media_diaria_150"].gt(0),
        result["estoque_apos_sugestao"] / result["media_diaria_150"],
        np.nan,
    )
    return result


def render_purchase_goal():
    st.title("🎯 Meta de Compra")
    st.caption(
        "Simule negociações extraordinárias por quantidade de peças ou por valor, "
        "respeitando estoque atual, pendências e limites de cobertura por curva."
    )

    with st.expander("Como o cálculo funciona", expanded=False):
        st.markdown(
            """
            **Cobertura projetada** = (Estoque atual + Pendências) ÷ média diária de 150 dias.

            **Estoque máximo** = média diária de 150 dias × limite da curva combinada.

            **Capacidade de compra** = Estoque máximo − Estoque atual − Pendências.

            A sugestão nunca ultrapassa a capacidade calculada de cada produto.
            """
        )

    st.markdown("### 1) Relatório")
    main_file = st.file_uploader(
        "Importe o relatório de giro e estoque",
        type=["xlsx", "xls", "csv"],
        key="goal_main_report",
        help=(
            "Aceita o formato com Codigo, Descrição, NumFabricante, Estoque do Grupo, "
            "Vendas 90 dias, Vendas 150 dias e Pendencias."
        ),
    )

    if main_file is None:
        st.info("Importe o relatório para iniciar a simulação.")
        return

    try:
        raw = _read_file(main_file)
        base = _standardize_report(raw)
    except Exception as exc:
        st.error(str(exc))
        return

    st.success(f"Relatório reconhecido: {len(base)} produtos.")

    with st.expander("Complemento de Curva ABC / valor unitário", expanded=False):
        st.caption(
            "O relatório principal pode continuar no formato atual. "
            "Se ele não tiver Curva ABC ou valor unitário, importe aqui um complemento "
            "com Codigo + Curva ABC e/ou Valor Unitário."
        )
        complement_file = st.file_uploader(
            "Arquivo complementar",
            type=["xlsx", "xls", "csv"],
            key="goal_complement",
        )

    try:
        complement = (
            _read_file(complement_file)
            if complement_file is not None
            else None
        )
        base = _merge_complement(base, complement)
    except Exception as exc:
        st.error(str(exc))
        return

    # Consolida as possíveis origens de ABC e valor.
    if "curva_abc_complemento" in base.columns:
        base["curva_abc"] = base["curva_abc_complemento"]
    elif "curva_abc_importada" in base.columns:
        base["curva_abc"] = base["curva_abc_importada"]
    else:
        base["curva_abc"] = ""

    if "valor_unitario_complemento" in base.columns:
        base["valor_unitario"] = base["valor_unitario_complemento"].fillna(
            base.get("valor_unitario", 0)
        )
    elif "valor_unitario" not in base.columns:
        base["valor_unitario"] = 0.0

    st.markdown("### 2) Curvas e limites")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Curva ABC — valor em 90 dias**")
        abc_a = st.number_input(
            "A até (%)",
            min_value=1.0,
            max_value=99.0,
            value=80.0,
            step=1.0,
            key="goal_abc_a",
        )
        abc_b = st.number_input(
            "B até (%)",
            min_value=float(abc_a),
            max_value=100.0,
            value=max(95.0, float(abc_a)),
            step=1.0,
            key="goal_abc_b",
        )

    with c2:
        st.markdown("**Curva PQR — unidades em 90 dias**")
        pqr_p = st.number_input(
            "P até (%)",
            min_value=1.0,
            max_value=99.0,
            value=80.0,
            step=1.0,
            key="goal_pqr_p",
        )
        pqr_q = st.number_input(
            "Q até (%)",
            min_value=float(pqr_p),
            max_value=100.0,
            value=max(95.0, float(pqr_p)),
            step=1.0,
            key="goal_pqr_q",
        )

    st.caption(
        "Se a Curva ABC vier pronta no arquivo, ela é preservada. "
        "Caso contrário, o NEXO calcula ABC com Vendas 90d × Valor Unitário."
    )

    limits = {}
    st.markdown("**Cobertura máxima por curva combinada**")
    limit_cols = st.columns(4)
    for idx, (curve, default_value) in enumerate(DEFAULT_LIMITS.items()):
        with limit_cols[idx % 4]:
            limits[curve] = st.number_input(
                f"{curve} (dias)",
                min_value=0,
                max_value=720,
                value=int(default_value),
                step=5,
                key=f"goal_limit_{curve}",
            )

    # PQR sempre pode ser calculada a partir do relatório.
    base["curva_pqr"], base["pqr_acumulado"] = _classify_with_ties(
        base["vendas_90"],
        pqr_p,
        pqr_q,
        ("P", "Q", "R"),
    )

    imported_abc_valid = base["curva_abc"].isin(["A", "B", "C"]).any()
    if not imported_abc_valid:
        if not base["valor_unitario"].gt(0).any():
            st.warning(
                "Para formar a Curva ABC, falta Curva ABC pronta ou Valor Unitário por código. "
                "Importe o complemento acima."
            )
            return
        abc_value = base["vendas_90"] * base["valor_unitario"]
        base["curva_abc"], base["abc_acumulado"] = _classify_with_ties(
            abc_value,
            abc_a,
            abc_b,
            ("A", "B", "C"),
        )
    else:
        base["curva_abc"] = base["curva_abc"].where(
            base["curva_abc"].isin(["A", "B", "C"]),
            "",
        )

    base["curva_combinada"] = base["curva_abc"] + base["curva_pqr"]
    base["limite_dias"] = base["curva_combinada"].map(limits)

    base["estoque_projetado"] = base["estoque"] + base["pendencias"]
    base["media_diaria_150"] = base["vendas_150"] / 150.0
    base["cobertura_projetada_dias"] = np.where(
        base["media_diaria_150"].gt(0),
        base["estoque_projetado"] / base["media_diaria_150"],
        np.nan,
    )
    base["estoque_maximo"] = (
        base["media_diaria_150"] * base["limite_dias"].fillna(0)
    )
    base["capacidade_compra"] = np.floor(
        np.maximum(base["estoque_maximo"] - base["estoque_projetado"], 0)
    )
    base.loc[base["limite_dias"].isna(), "capacidade_compra"] = 0
    base["capacidade_valor"] = base["capacidade_compra"] * base["valor_unitario"]

    without_rule = sorted(
        curve
        for curve in base.loc[
            base["limite_dias"].isna(), "curva_combinada"
        ].dropna().unique()
        if curve
    )
    if without_rule:
        st.warning(
            "Curvas sem critério de cobertura: "
            + ", ".join(without_rule)
            + ". Esses produtos ficam com capacidade de compra igual a zero."
        )

    st.markdown("### 3) Meta da negociação")
    m1, m2, m3 = st.columns([1.2, 1.2, 1.5])
    mode = m1.radio(
        "Tipo de meta",
        ["Meta por peças", "Meta por valor"],
        horizontal=False,
        key="goal_mode",
    )

    if mode == "Meta por peças":
        target = m2.number_input(
            "Meta de peças",
            min_value=0,
            value=11500,
            step=100,
            key="goal_piece_target",
        )
    else:
        target = m2.number_input(
            "Meta em R$",
            min_value=0.0,
            value=0.0,
            step=1000.0,
            format="%.2f",
            key="goal_value_target",
        )

    order_rule = m3.selectbox(
        "Distribuir priorizando",
        [
            "Menor cobertura primeiro",
            "Maior giro (P → Q → R)",
            "Maior capacidade disponível",
        ],
        key="goal_order_rule",
    )

    if mode == "Meta por valor" and not base["valor_unitario"].gt(0).any():
        st.warning(
            "Meta por valor precisa de Valor Unitário por código no relatório "
            "ou no arquivo complementar."
        )
        return

    result = _allocate_goal(base, mode, target, order_rule)

    total_capacity_pieces = int(result["capacidade_compra"].sum())
    total_capacity_value = float(result["capacidade_valor"].sum())
    suggested_pieces = int(result["qtd_sugerida"].sum())
    suggested_value = float(result["valor_sugerido"].sum())

    if mode == "Meta por peças":
        achieved = suggested_pieces
        gap = max(float(target) - achieved, 0)
        capacity_display = f"{total_capacity_pieces:,.0f}".replace(",", ".")
        target_display = f"{float(target):,.0f}".replace(",", ".")
        achieved_display = f"{achieved:,.0f}".replace(",", ".")
        gap_display = f"{gap:,.0f}".replace(",", ".")
    else:
        achieved = suggested_value
        gap = max(float(target) - achieved, 0)
        capacity_display = (
            f"R$ {total_capacity_value:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
        target_display = (
            f"R$ {float(target):,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
        achieved_display = (
            f"R$ {achieved:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
        gap_display = (
            f"R$ {gap:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Meta", target_display)
    k2.metric("Capacidade máxima", capacity_display)
    k3.metric("Sugestão calculada", achieved_display)
    k4.metric("Falta para meta", gap_display)

    if gap > 0:
        st.warning(
            "A meta é maior do que a quantidade/valor que cabe nos limites atuais "
            "ou não pôde ser completada exatamente com os valores unitários disponíveis."
        )
    else:
        st.success("A meta cabe dentro dos limites de cobertura configurados.")

    st.markdown("### 4) Sugestão por produto")
    display = result[
        [
            "codigo",
            "referencia",
            "descricao",
            "curva_abc",
            "curva_pqr",
            "curva_combinada",
            "estoque",
            "pendencias",
            "estoque_projetado",
            "vendas_90",
            "vendas_150",
            "cobertura_projetada_dias",
            "limite_dias",
            "capacidade_compra",
            "valor_unitario",
            "capacidade_valor",
            "qtd_sugerida",
            "valor_sugerido",
            "cobertura_apos_sugestao",
        ]
    ].copy()

    display.columns = [
        "Código",
        "Referência",
        "Descrição",
        "ABC",
        "PQR",
        "Curva",
        "Estoque Atual",
        "Pendências",
        "Estoque Projetado",
        "Vendas 90d",
        "Vendas 150d",
        "Cobertura Atual + Pend. (dias)",
        "Limite (dias)",
        "Capacidade Compra",
        "Valor Unitário",
        "Capacidade em R$",
        "Qtd Sugerida",
        "Valor Sugerido",
        "Cobertura Após Sugestão",
    ]

    only_suggested = st.checkbox(
        "Mostrar somente produtos com sugestão de compra",
        value=True,
        key="goal_only_suggested",
    )
    view = display[
        display["Qtd Sugerida"].gt(0)
    ].copy() if only_suggested else display

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Cobertura Atual + Pend. (dias)": st.column_config.NumberColumn(format="%.1f"),
            "Cobertura Após Sugestão": st.column_config.NumberColumn(format="%.1f"),
            "Valor Unitário": st.column_config.NumberColumn(format="R$ %.2f"),
            "Capacidade em R$": st.column_config.NumberColumn(format="R$ %.2f"),
            "Valor Sugerido": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

    config_rows = [
        {"Parâmetro": "Tipo de meta", "Valor": mode},
        {"Parâmetro": "Meta", "Valor": target},
        {"Parâmetro": "Distribuição", "Valor": order_rule},
        {"Parâmetro": "ABC A até (%)", "Valor": abc_a},
        {"Parâmetro": "ABC B até (%)", "Valor": abc_b},
        {"Parâmetro": "PQR P até (%)", "Valor": pqr_p},
        {"Parâmetro": "PQR Q até (%)", "Valor": pqr_q},
    ]
    config_rows.extend(
        {"Parâmetro": f"Limite {curve} (dias)", "Valor": value}
        for curve, value in limits.items()
    )
    config = pd.DataFrame(config_rows)

    st.download_button(
        "⬇️ Exportar simulação (.xlsx)",
        data=_xlsx_bytes(display, config),
        file_name="NEXO_simulacao_meta_compra.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

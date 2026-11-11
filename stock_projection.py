import io
from datetime import date, timedelta
import pandas as pd
import streamlit as st


def render_projection(products, period_days, classify_coverage, criteria):
    st.markdown("### Projeção de estoque por data")
    st.caption("Estimativa baseada no estoque atual e na média de vendas do período analisado. A data-base é hoje.")
    target = st.date_input("Projetar estoque para", value=date.today() + timedelta(days=90),
                           min_value=date.today(), format="DD/MM/YYYY", key="projection_target")
    days = (target - date.today()).days
    use_orders = st.checkbox("Considerar compras pendentes (opcional)", value=False, key="projection_orders")
    orders = pd.DataFrame(columns=["Codigo", "Quantidade", "Chegada"])
    if use_orders:
        st.caption("Importe CSV ou XLSX com as colunas Codigo, Quantidade e Chegada (AAAA-MM-DD).")
        template = pd.DataFrame({"Codigo": ["EXEMPLO"], "Quantidade": [10], "Chegada": ["2027-01-15"]})
        st.download_button("Baixar modelo de compras", template.to_csv(index=False).encode("utf-8-sig"),
                           file_name="modelo_compras_pendentes.csv", mime="text/csv")
        upload = st.file_uploader("Compras pendentes", type=["csv", "xlsx"], key="projection_upload")
        if upload is not None:
            try:
                orders = pd.read_csv(upload, dtype={"Codigo": str}) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, dtype={"Codigo": str})
                if not {"Codigo", "Quantidade", "Chegada"}.issubset(orders.columns):
                    raise ValueError("Colunas necessárias: Codigo, Quantidade, Chegada.")
                orders = orders[["Codigo", "Quantidade", "Chegada"]].copy()
                orders["Codigo"] = orders["Codigo"].astype(str).str.strip().str.replace(r"\\.0$", "", regex=True)
                orders["Quantidade"] = pd.to_numeric(orders["Quantidade"], errors="coerce")
                orders["Chegada"] = pd.to_datetime(orders["Chegada"], errors="coerce", format="%Y-%m-%d")
                if orders["Codigo"].eq("").any() or orders["Quantidade"].isna().any() or (orders["Quantidade"] <= 0).any() or orders["Chegada"].isna().any():
                    raise ValueError("Existem códigos, quantidades ou datas inválidos.")
                orders = orders[(orders["Chegada"].dt.date >= date.today()) & (orders["Chegada"].dt.date <= target)]
                st.caption(f"Entregas consideradas até a data: {len(orders)}")
            except Exception as exc:
                st.error(f"Erro nas compras pendentes: {exc}")
                return
    forecast = products[["codigo", "descricao", "linha", "curva_abc", "estoque", "vendas_periodo"]].copy()
    forecast["codigo"] = forecast["codigo"].astype(str).str.strip().str.replace(r"\\.0$", "", regex=True)
    forecast["Consumo previsto"] = forecast["vendas_periodo"].clip(lower=0) / period_days * days
    totals = orders.groupby("Codigo")["Quantidade"].sum() if not orders.empty else pd.Series(dtype=float)
    forecast["Compras previstas"] = forecast["codigo"].map(totals).fillna(0)
    forecast["Saldo estimado"] = forecast["estoque"] - forecast["Consumo previsto"] + forecast["Compras previstas"]
    forecast["Estoque futuro"] = forecast["Saldo estimado"].clip(lower=0)
    forecast["Falta estimada"] = (-forecast["Saldo estimado"]).clip(lower=0)
    forecast["Situação futura"] = [
        classify_coverage(float(stock), float(sales), period_days, curve, criteria)
        for stock, sales, curve in zip(forecast["Estoque futuro"], forecast["vendas_periodo"], forecast["curva_abc"])
    ]
    a, b, c, d = st.columns(4)
    a.metric("Dias projetados", days)
    b.metric("Estoque futuro (un.)", f'{forecast["Estoque futuro"].sum():,.0f}'.replace(",", "."))
    c.metric("Produtos em ruptura", int((forecast["Situação futura"] == "RUPTURA").sum()))
    d.metric("Falta estimada (un.)", f'{forecast["Falta estimada"].sum():,.0f}'.replace(",", "."))
    st.caption("Projeção individual por SKU. Compras são somadas somente se informadas e com chegada até a data escolhida. Não simula rupturas intermediárias, sazonalidade ou mudanças de demanda.")
    report = forecast.rename(columns={"codigo": "Código", "descricao": "Descrição", "linha": "Linha",
        "curva_abc": "Curva ABC", "estoque": "Estoque atual", "vendas_periodo": "Vendas no período"})
    with st.expander("Ver estoque projetado por produto"):
        st.dataframe(report, hide_index=True, use_container_width=True)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        report.to_excel(writer, sheet_name="PROJECAO", index=False)
        ws = writer.book["PROJECAO"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(40, max(14, max(len(str(c.value or "")) for c in col[:150]) + 2))
        pd.DataFrame({"Campo": ["Data projetada", "Período de vendas (dias)", "Metodologia"],
                      "Valor": [target.strftime("%d/%m/%Y"), period_days,
                      "Estoque atual - consumo médio diário x dias + compras com chegada até a data"]}).to_excel(
                          writer, sheet_name="METODOLOGIA", index=False)
    st.download_button("Baixar projeção em Excel", out.getvalue(),
        file_name=f"projecao_estoque_{target.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

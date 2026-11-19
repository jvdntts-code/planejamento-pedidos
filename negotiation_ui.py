"""Interface independente para negociar meta de peças sem meta de cobertura."""
import pandas as pd
import streamlit as st

from coverage_planning import import_abc_snapshot
from discount_planning import (
    build_negotiation_inputs, load_unit_costs, simulate_discount_negotiation
)


def render_negotiation(
    base, needs, order, origem_abc, arquivo_abc, snapshot_calculado,
    leadtime_dias, pend_map, confirmar_pendencias, considerar_m20,
    meta_fornecedor, percentual_desconto, arquivo_custo,
    read_file, xlsx_bytes
):
    st.markdown("### Planejador de negociação — meta em peças")
    st.caption(
        f"Objetivo: distribuir até {int(meta_fornecedor):,} peças, "
        "priorizando Curva A → B → C. Sem metas ou teto de dias: "
        "a cobertura após a compra é calculada e exibida para conferência."
    )
    if origem_abc == "Arquivo do sistema":
        snapshot = None
        if arquivo_abc is not None:
            try:
                snapshot = import_abc_snapshot(read_file(arquivo_abc))
            except ValueError as exc:
                st.error(f"Arquivo de Curva ABC inválido: {exc}")
        if snapshot is None and arquivo_abc is None:
            st.info(
                "Na lateral, importe Vendas Produtos com Código, Marca e "
                "Curva ABC. Não é necessário preço de venda para usar a "
                "classificação fornecida pelo sistema."
            )
            return
    else:
        snapshot = snapshot_calculado
        if not snapshot:
            st.info(
                "Abra Análise de Linha e calcule a Curva ABC antes de "
                "simular a negociação, ou selecione Arquivo do sistema."
            )
            return

    if snapshot is None:
        return
    st.caption(
        f"Curva ABC: {snapshot['brand']} — "
        + (
            "importada do sistema, sem depender de preço de venda."
            if snapshot.get("source") == "imported"
            else "calculada na Análise de Linha."
        )
    )
    if snapshot.get("duplicates"):
        st.warning(
            f"{len(snapshot['duplicates'])} código(s) repetido(s) no arquivo ABC "
            "foram consolidados. Confira os registros na origem."
        )
    if snapshot.get("skipped_rows") or snapshot.get("missing_curves"):
        st.warning(
            "Alguns registros do arquivo ABC não tinham código, marca "
            "ou classificação A/B/C válida e foram ignorados."
        )

    try:
        cost_map = None
        cost_invalid = []
        if arquivo_custo is not None:
            cost_map, cost_invalid = load_unit_costs(read_file(arquivo_custo))
        normal = build_negotiation_inputs(
            base, needs, order, snapshot, leadtime_dias,
            pending_by_code=pend_map,
            include_pending=bool(confirmar_pendencias),
            include_m20=bool(considerar_m20),
        )
        result = simulate_discount_negotiation(
            normal,
            limit_units=int(meta_fornecedor),
            discount_pct=float(percentual_desconto),
            unit_costs=cost_map,
        )
    except (ValueError, TypeError) as exc:
        st.error(f"Não foi possível simular a negociação: {exc}")
        return

    a, b, c, d = st.columns(4)
    a.metric("Meta do fornecedor", f"{result['target_units']:,}".replace(",", "."))
    b.metric(
        "Compra inicial — método atual",
        f"{result['normal_units']:,}".replace(",", "."),
    )
    c.metric("Peças distribuídas", f"{result['proposed_units']:,}".replace(",", "."))
    d.metric("Faltam para meta", f"{result['remaining_units']:,}".replace(",", "."))

    if result["discount_achieved"]:
        st.success(
            "A simulação atingiu exatamente a meta de peças. "
            f"O desconto de {percentual_desconto:g}% sobre o pedido inteiro "
            "poderá ser considerado se as condições forem confirmadas pelo fornecedor."
        )
    else:
        st.warning(
            "A meta não foi atingida exatamente com as embalagens e SKUs elegíveis. "
            f"Faltam {result['remaining_units']:,} peças. "
            "O desconto não foi aplicado na comparação financeira."
        )
    if not result["normal_fully_covered"]:
        st.warning(
            "A meta informada é menor que a compra inicial calculada. "
            "A distribuição não inclui unidades extras enquanto houver "
            "necessidade inicial não atendida."
        )
    st.caption(
        f"{result['extra_units']:,} unidades adicionais para tentar fechar a meta · "
        f"{result['proposed_skus']} produtos com compra · "
        f"{result['blocked_skus']} registros pendentes de conferência. "
        "A compra inicial considera o método tradicional e as pendências "
        "apenas quando confirmadas para o prazo. A distribuição adicional "
        "prioriza a menor cobertura dentro da Curva A, depois B e C."
    )

    st.markdown("#### Quantidade distribuída e cobertura após a compra")
    table = result["table"]
    buy_mask = pd.to_numeric(
        table["Compra proposta (peças)"], errors="coerce"
    ).fillna(0).gt(0)
    proposal = table.loc[buy_mask].copy()
    columns = [
        "Código", "Referência", "Descrição", "Curva ABC",
        "Necessidade normal (peças)", "Peças extras para desconto",
        "Compra proposta (peças)", "Embalagem",
        "Vendas 90d filiais", "Estoque filiais", "Estoque M20",
        "Cobertura atual (dias)", "Cobertura na chegada (dias)",
        "Estoque projetado após compra (peças)",
        "Cobertura proposta (dias)", "Aumento de cobertura (dias)",
        "Alerta de cobertura", "Resultado",
    ]
    if proposal.empty:
        st.info("Nenhum produto apto recebeu unidades nesta simulação.")
    else:
        view = proposal[columns].sort_values(
            ["Curva ABC", "Cobertura proposta (dias)"],
            ascending=[True, True], kind="stable",
        )
        st.dataframe(
            view, use_container_width=True, hide_index=True,
            column_config={
                "Cobertura proposta (dias)": st.column_config.NumberColumn(
                    "Cobertura após compra (dias)", format="%.1f"
                ),
                "Cobertura na chegada (dias)": st.column_config.NumberColumn(
                    format="%.1f"
                ),
                "Cobertura atual (dias)": st.column_config.NumberColumn(
                    format="%.1f"
                ),
                "Aumento de cobertura (dias)": st.column_config.NumberColumn(
                    format="%.1f"
                ),
            },
        )
    if result["above_180_skus"]:
        st.warning(
            f"{result['above_180_skus']} produtos terão mais de 180 dias de "
            f"cobertura, incluindo {result['above_365_skus']} acima de 365 dias. "
            "Esses valores não limitam as quantidades sugeridas; servem para "
            "você decidir se o desconto compensa o estoque adicional."
        )
    if leadtime_dias == 0:
        st.info(
            "Lead time está em 0 dia: ajuste o prazo na barra lateral "
            "para projetar a cobertura no recebimento."
        )
    if cost_invalid:
        st.warning(
            f"{len(cost_invalid)} código(s) com custo inválido no arquivo "
            "não entraram no cálculo financeiro."
        )
    if result["financial"] is None:
        if arquivo_custo is None:
            st.info(
                "Sem custo unitário importado, o resultado compara somente "
                "quantidades e dias. Para avaliar o desconto de 5% em reais, "
                "importe opcionalmente Código e Custo Unitário."
            )
        else:
            st.warning(
                f"{len(result['missing_cost_codes'])} código(s) comprados ou "
                "incluídos na compra inicial estão sem custo válido. "
                "Não será apresentada economia fictícia."
            )
    else:
        st.markdown("#### Avaliação financeira (se houver custos confiáveis)")
        fin = result["financial"]
        amounts = st.columns(4)
        amounts[0].metric(
            "Compra inicial", f"R$ {fin['Compra normal sem desconto (R$)']:,.2f}"
        )
        amounts[1].metric(
            "Proposta antes do desconto", f"R$ {fin['Proposta antes do desconto (R$)']:,.2f}"
        )
        amounts[2].metric(
            "Desconto condicionado à meta", f"R$ {fin['Desconto condicional (R$)']:,.2f}"
        )
        amounts[3].metric(
            "Proposta após desconto", f"R$ {fin['Proposta após desconto (R$)']:,.2f}"
        )
        st.caption(
            "Diferença de desembolso frente à compra inicial: "
            f"R$ {fin['Diferença de desembolso (R$)']:,.2f}. "
            "Não contempla custo financeiro, sazonalidade, impostos ou armazenagem."
        )

    st.caption(
        "Cobertura aproximada: (estoques das filiais incluídas + M20 considerada "
        "+ pendência confirmada − vendas esperadas durante o lead time "
        "+ compra sugerida) ÷ consumo médio diário. "
        "Saldos negativos projetados são exibidos como risco de falta antes da "
        "chegada. A cobertura é consolidada e não garante disponibilidade "
        "em cada filial. Sem teto de dias, uma meta alta pode criar estoques "
        "excessivos. A sugestão é para avaliação, não um pedido automático."
    )
    with st.expander("Conferir todos os produtos e memória do cálculo", expanded=False):
        st.dataframe(table, use_container_width=True, hide_index=True)
        if result["missing_cost_codes"]:
            st.caption(
                "Códigos sem custo válido: "
                + ", ".join(result["missing_cost_codes"][:40])
            )
    params = pd.DataFrame({
        "Parâmetro": [
            "Meta de peças", "Desconto (%)", "Origem Curva ABC",
            "Lead time (dias)", "M20 considerada",
            "Pendências confirmadas",
            "Critério de distribuição",
            "Resultado da meta comercial",
        ],
        "Valor": [
            meta_fornecedor, percentual_desconto,
            snapshot.get("source_label", "Calculada na Análise de Linha"),
            leadtime_dias, "Sim" if considerar_m20 else "Não",
            "Sim" if confirmar_pendencias else "Não",
            "Sem limite de dias; A depois B e C; embalagens inteiras",
            "Atingida" if result["discount_achieved"] else "Não atingida",
        ],
    })
    sheets = {
        "Compra para Desconto": proposal[columns],
        "Memoria Completa": table,
        "Parametros": params,
    }
    if result["financial"] is not None:
        sheets["Financeiro"] = pd.DataFrame([result["financial"]])
    st.download_button(
        "Exportar distribuição e coberturas (.xlsx)",
        data=xlsx_bytes(sheets),
        file_name="NEXO_negociacao_meta_pecas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="nexo_negociacao_meta_download",
    )

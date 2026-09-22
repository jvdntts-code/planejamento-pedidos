import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pypdf import PdfReader


NAVY = "17365D"
WHITE = "FFFFFF"


def br_to_float(value):
    if value is None:
        return 0.0
    text = str(value).strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return 0.0


def money_br(value):
    return (
        f"R$ {float(value):,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def extract_pdf_text(uploaded):
    raw = uploaded.getvalue()
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    full_text = "\n".join(pages).strip()
    if not full_text:
        raise ValueError(
            "Não consegui extrair texto deste PDF. "
            "Este primeiro modelo funciona com PDFs gerados pelo sistema, que possuem texto selecionável."
        )
    return full_text, len(reader.pages)


def _smart_join_item_lines(lines):
    """Reconstrói itens que quebraram em duas ou três linhas durante a leitura do PDF."""
    rebuilt = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not re.match(r"^PC\d+", line, flags=re.IGNORECASE):
            i += 1
            continue

        buffer = line
        j = i + 1

        while (
            not re.search(r"\d{6}$", buffer)
            and j < len(lines)
            and not re.match(r"^PC\d+", lines[j].strip(), flags=re.IGNORECASE)
            and "TOTAL BRUTO" not in lines[j].upper()
        ):
            next_line = lines[j].strip()

            # Corrige palavras quebradas pelo PDF, por exemplo:
            # "TERMINA" + "IS" -> "TERMINAIS"; "FURO" + "S" -> "FUROS".
            if (
                re.fullmatch(r"[A-Za-zÀ-ÿ]{1,3}", next_line)
                and re.search(r"[A-Za-zÀ-ÿ]$", buffer)
            ):
                buffer += next_line
            else:
                buffer += " " + next_line
            j += 1

        rebuilt.append(buffer)
        i = j

    return rebuilt


def parse_items(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    item_lines = _smart_join_item_lines(lines)

    # Formato observado no PDF do sistema:
    # PC25 0,0044099001 36,38 0,00 DESCRICAO000139
    #   PC = unidade
    #   25 = quantidade
    #   0,00 = IPI
    #   44099 = número do fabricante
    #   001 = número do item
    #   36,38 = valor unitário
    #   0,00 = desconto
    #   000139 = código interno
    pattern = re.compile(
        r"^PC(?P<qtd>\d+(?:[.,]\d+)?)\s+"
        r"(?P<ipi>\d+,\d{2})"
        r"(?P<fabricante_item>[A-Z0-9]+?)"
        r"(?P<item>\d{3})\s+"
        r"(?P<valor_unitario>\d+,\d{2})\s+"
        r"(?P<desconto>\d+,\d{2})\s+"
        r"(?P<descricao>.+?)"
        r"(?P<codigo>\d{6})$",
        flags=re.IGNORECASE,
    )

    rows = []
    not_parsed = []

    for raw_line in item_lines:
        match = pattern.match(raw_line)
        if not match:
            not_parsed.append(raw_line)
            continue

        data = match.groupdict()
        fabricante_item = data["fabricante_item"].strip()
        qtd = br_to_float(data["qtd"])
        valor_unitario = br_to_float(data["valor_unitario"])
        desconto = br_to_float(data["desconto"])
        ipi = br_to_float(data["ipi"])

        rows.append(
            {
                "Item": int(data["item"]),
                "Codigo": data["codigo"],
                "Nr Fabricante": fabricante_item,
                "Descricao": re.sub(r"\s+", " ", data["descricao"]).strip(),
                "Qtd Pedida": qtd,
                "D/U": "PC",
                "Vl Unitario": valor_unitario,
                "% Desc": desconto,
                "% IPI": ipi,
                "Valor Item": qtd * valor_unitario,
                "Qtd Recebida": 0.0,
                "Qtd Pendente": qtd,
                "Status": "EM ABERTO",
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Item").reset_index(drop=True)

    return df, not_parsed


def parse_order_header(text):
    supplier_match = re.search(
        r"\b(F\d{6})\s+([A-ZÀ-ÿ0-9 .&/-]+?LTDA)\b",
        text,
        flags=re.IGNORECASE,
    )
    order_match = re.search(r"S/PEDIDO\.*:\s*(\d+)", text, flags=re.IGNORECASE)

    date_match = re.search(
        r"DATA PEDIDO\.*:\s*(?:\S+\s*)?(\d{2}/\d{2}/\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if not date_match:
        date_match = re.search(
            r"EMISS[ÃA]O\s*:\s*(\d{2}/\d{2}/\d{4})",
            text,
            flags=re.IGNORECASE,
        )

    total_match = re.search(
        r"VALOR PEDIDO\.*:\s*(?:% DESC\s*)?([\d.]+,\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if not total_match:
        total_match = re.search(
            r"TOTAL LIQUIDO DO PEDIDO-->\s*(?:.*?\n)*?([\d.]+,\d{2})",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    buyer_match = re.search(
        r"COMPRADOR\.*:\s*([^\n]+)",
        text,
        flags=re.IGNORECASE,
    )

    supplier_code = supplier_match.group(1).upper() if supplier_match else ""
    supplier_name = supplier_match.group(2).strip().upper() if supplier_match else ""
    order_number = order_match.group(1) if order_match else ""
    order_date = date_match.group(1) if date_match else ""
    total_value = br_to_float(total_match.group(1)) if total_match else 0.0
    buyer = buyer_match.group(1).strip() if buyer_match else ""

    return {
        "Fornecedor Codigo": supplier_code,
        "Fornecedor": supplier_name,
        "Pedido": order_number,
        "Data Pedido": order_date,
        "Valor Pedido": total_value,
        "Comprador": buyer,
    }


def calculate_next_cycle(order_date, months=2):
    try:
        dt = datetime.strptime(order_date, "%d/%m/%Y")
    except Exception:
        return None
    return (pd.Timestamp(dt) + pd.DateOffset(months=months)).date()


def parse_order_pdf(uploaded):
    text, pages = extract_pdf_text(uploaded)
    header = parse_order_header(text)
    items, not_parsed = parse_items(text)

    if items.empty:
        raise ValueError(
            "O PDF foi lido, mas nenhum item foi reconhecido. "
            "O layout pode ser diferente do modelo de Pedido Fornecedor usado na configuração inicial."
        )

    header["Paginas"] = pages
    header["Itens"] = len(items)
    header["Quantidade Total"] = float(items["Qtd Pedida"].sum())
    header["Valor Calculado Itens"] = float(items["Valor Item"].sum())
    header["Proxima Compra"] = calculate_next_cycle(header["Data Pedido"], 2)

    return header, items, not_parsed, text


def update_receipt_columns(df):
    x = df.copy()
    x["Qtd Pedida"] = pd.to_numeric(x["Qtd Pedida"], errors="coerce").fillna(0)
    x["Qtd Recebida"] = pd.to_numeric(x["Qtd Recebida"], errors="coerce").fillna(0)
    x["Qtd Recebida"] = x[["Qtd Recebida", "Qtd Pedida"]].min(axis=1).clip(lower=0)
    x["Qtd Pendente"] = (x["Qtd Pedida"] - x["Qtd Recebida"]).clip(lower=0)

    x["Status"] = "EM ABERTO"
    x.loc[x["Qtd Recebida"] > 0, "Status"] = "PARCIAL"
    x.loc[x["Qtd Pendente"] <= 0, "Status"] = "RECEBIDO"
    return x


def export_order_xlsx(header, items):
    summary = pd.DataFrame(
        {
            "Campo": [
                "Fornecedor",
                "Código Fornecedor",
                "Pedido",
                "Data Pedido",
                "Próxima Compra",
                "Valor Pedido",
                "Quantidade de Itens",
                "Quantidade Total",
                "Valor Calculado dos Itens",
            ],
            "Valor": [
                header.get("Fornecedor", ""),
                header.get("Fornecedor Codigo", ""),
                header.get("Pedido", ""),
                header.get("Data Pedido", ""),
                (
                    header.get("Proxima Compra").strftime("%d/%m/%Y")
                    if header.get("Proxima Compra") is not None
                    else ""
                ),
                header.get("Valor Pedido", 0),
                len(items),
                float(items["Qtd Pedida"].sum()) if not items.empty else 0,
                float(items["Valor Item"].sum()) if not items.empty else 0,
            ],
        }
    )

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="PEDIDO", index=False)
        items.to_excel(writer, sheet_name="ITENS", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.sheet_view.showGridLines = False
            ws.auto_filter.ref = ws.dimensions

            for cell in ws[1]:
                cell.font = Font(name="Times New Roman", bold=True, color=WHITE)
                cell.fill = PatternFill("solid", fgColor=NAVY)
                cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True,
                )

            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.font = Font(name="Times New Roman", size=11)
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

            for col in ws.columns:
                letter = get_column_letter(col[0].column)
                max_len = max([len(str(cell.value or "")) for cell in col[:400]] + [10])
                ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 46)

    out.seek(0)
    return out.getvalue()


def render_gestao_pedidos():
    st.title("🧾 Gestão de Pedidos")
    st.caption(
        "Importe o PDF do Pedido Fornecedor e transforme o documento em acompanhamento de compra."
    )

    with st.expander("📘 Como funciona", expanded=False):
        st.markdown(
            """
            1. Importe o **PDF original do Pedido Fornecedor**.
            2. O NEXO lê fornecedor, número do pedido, data, valor e itens.
            3. Confira os dados extraídos antes de utilizá-los.
            4. A tabela de itens permite informar **Qtd Recebida** para acompanhar recebimentos parciais.
            5. Para fornecedores com ciclo bimestral, o NEXO mostra a **próxima compra prevista em 2 meses**.

            Esta primeira versão foi preparada para o layout do Pedido Fornecedor usado como modelo inicial.
            """
        )

    uploaded = st.file_uploader(
        "Importar Pedido Fornecedor em PDF",
        type=["pdf"],
        key="gestao_pedido_pdf",
        help="Use o PDF original gerado pelo sistema.",
    )

    if not uploaded:
        st.info("Envie um PDF de pedido para começar.")
        return

    try:
        header, items, not_parsed, extracted_text = parse_order_pdf(uploaded)
    except Exception as exc:
        st.error(str(exc))
        return

    st.success(
        f"Pedido reconhecido: {header.get('Pedido') or 'sem número'} | "
        f"{header.get('Itens', 0)} item(ns) extraído(s)."
    )

    if not_parsed:
        st.warning(
            f"{len(not_parsed)} linha(s) com aparência de item não foram interpretadas. "
            "Confira a tabela antes de continuar."
        )

    st.markdown("### Visão geral")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pedido", header.get("Pedido") or "—")
    c2.metric("Fornecedor", header.get("Fornecedor") or "—")
    c3.metric("Valor do pedido", money_br(header.get("Valor Pedido", 0)))
    c4.metric("Itens", int(header.get("Itens", 0)))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Data do pedido", header.get("Data Pedido") or "—")
    next_cycle = header.get("Proxima Compra")
    c6.metric(
        "Próxima compra (2 meses)",
        next_cycle.strftime("%d/%m/%Y") if next_cycle is not None else "—",
    )
    c7.metric(
        "Quantidade total",
        f"{header.get('Quantidade Total', 0):,.0f}".replace(",", "."),
    )
    c8.metric(
        "Valor calculado pelos itens",
        money_br(header.get("Valor Calculado Itens", 0)),
    )

    pdf_total = float(header.get("Valor Pedido", 0) or 0)
    item_total = float(header.get("Valor Calculado Itens", 0) or 0)
    if pdf_total and abs(pdf_total - item_total) <= 0.02:
        st.success("✅ O valor somado dos itens confere com o valor total do PDF.")
    elif pdf_total:
        st.warning(
            "⚠️ O valor somado dos itens não confere com o total informado no PDF. "
            f"Diferença: {money_br(item_total - pdf_total)}."
        )

    st.markdown("### Itens do pedido")
    st.caption(
        "Você pode preencher a coluna **Qtd Recebida**. "
        "O saldo pendente e o status são recalculados logo abaixo."
    )

    editor_key = f"order_items_{header.get('Pedido')}_{uploaded.name}"
    edited = st.data_editor(
        items,
        use_container_width=True,
        hide_index=True,
        key=editor_key,
        disabled=[
            "Item",
            "Codigo",
            "Nr Fabricante",
            "Descricao",
            "Qtd Pedida",
            "D/U",
            "Vl Unitario",
            "% Desc",
            "% IPI",
            "Valor Item",
            "Qtd Pendente",
            "Status",
        ],
        column_config={
            "Qtd Recebida": st.column_config.NumberColumn(
                "Qtd Recebida",
                min_value=0.0,
                step=1.0,
            ),
            "Vl Unitario": st.column_config.NumberColumn(
                "Vl Unitario",
                format="R$ %.2f",
            ),
            "Valor Item": st.column_config.NumberColumn(
                "Valor Item",
                format="R$ %.2f",
            ),
        },
    )

    managed = update_receipt_columns(edited)

    received_qty = float(managed["Qtd Recebida"].sum())
    pending_qty = float(managed["Qtd Pendente"].sum())
    received_items = int((managed["Status"] == "RECEBIDO").sum())
    partial_items = int((managed["Status"] == "PARCIAL").sum())

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Qtd recebida", f"{received_qty:,.0f}".replace(",", "."))
    r2.metric("Qtd pendente", f"{pending_qty:,.0f}".replace(",", "."))
    r3.metric("Itens recebidos", received_items)
    r4.metric("Itens parciais", partial_items)

    with st.expander("Ver acompanhamento atualizado"):
        st.dataframe(
            managed[
                [
                    "Item",
                    "Codigo",
                    "Nr Fabricante",
                    "Descricao",
                    "Qtd Pedida",
                    "Qtd Recebida",
                    "Qtd Pendente",
                    "Status",
                    "Vl Unitario",
                    "Valor Item",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.download_button(
        "📥 Exportar pedido para Excel",
        data=export_order_xlsx(header, managed),
        file_name=f"NEXO_pedido_{header.get('Pedido') or 'importado'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary",
        key="export_order_xlsx",
    )

    with st.expander("🔧 Diagnóstico da leitura do PDF"):
        st.caption(
            "Use esta área apenas se algum dado não for reconhecido corretamente em outro modelo de pedido."
        )
        st.text_area(
            "Texto extraído",
            extracted_text,
            height=220,
            disabled=True,
            key="order_extracted_text",
        )

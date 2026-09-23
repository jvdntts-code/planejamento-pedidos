import base64
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

import pandas as pd
import streamlit as st
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pypdf import PdfReader


NAVY = "17365D"
WHITE = "FFFFFF"

ORDERS_INDEX_PATH = "orders/index.json"
DEFAULT_DATA_BRANCH = "main"


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
    raw = uploaded if isinstance(uploaded, (bytes, bytearray)) else uploaded.getvalue()
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
    header["Proxima Compra"] = None
    header["Ciclo Meses"] = None

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
                "Ciclo entre compras (meses)",
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
                header.get("Ciclo Meses", ""),
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


def _get_secret(name, default=""):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def _data_settings():
    repo = str(_get_secret("GITHUB_DATA_REPO", "")).strip()
    branch = str(
        _get_secret(
            "GITHUB_DATA_BRANCH",
            _get_secret("GITHUB_BRANCH", DEFAULT_DATA_BRANCH),
        )
    ).strip()
    token = str(_get_secret("GITHUB_TOKEN", "")).strip()
    return repo, branch or DEFAULT_DATA_BRANCH, token


def _github_headers(token=""):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nexo-gestao-pedidos",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _data_repo_status():
    cache_key = "gestao_data_repo_status"
    settings = _data_settings()
    cached = st.session_state.get(cache_key)
    if cached and cached.get("settings") == settings:
        return cached["ready"], cached["message"]

    repo, _, token = settings
    if not repo:
        result = (
            False,
            "Configure GITHUB_DATA_REPO com um repositório privado para ativar o salvamento permanente.",
        )
    elif not token:
        result = (
            False,
            "GITHUB_TOKEN não está configurado para o repositório privado de dados.",
        )
    else:
        url = f"https://api.github.com/repos/{repo}"
        request = urllib.request.Request(
            url,
            headers=_github_headers(token),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not bool(payload.get("private")):
                result = (
                    False,
                    "O repositório definido em GITHUB_DATA_REPO não é privado. "
                    "Por segurança, o NEXO não gravará pedidos nele.",
                )
            else:
                result = (True, f"Salvamento permanente ativo em {repo}.")
        except urllib.error.HTTPError as exc:
            result = (
                False,
                f"Não foi possível acessar o repositório privado de dados (HTTP {exc.code}).",
            )
        except Exception as exc:
            result = (False, f"Não foi possível validar o repositório privado: {exc}")

    st.session_state[cache_key] = {
        "settings": settings,
        "ready": result[0],
        "message": result[1],
    }
    return result


def _github_read_bytes(path):
    ready, message = _data_repo_status()
    if not ready:
        return None, None, message

    repo, branch, token = _data_settings()
    encoded_path = urllib.parse.quote(path, safe="/")
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
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = base64.b64decode(payload.get("content", ""))
        return data, payload.get("sha"), None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None, None
        return None, None, f"GitHub respondeu HTTP {exc.code} ao ler {path}."
    except Exception as exc:
        return None, None, f"Não foi possível ler {path}: {exc}"


def _github_write_bytes(path, data, message):
    ready, status_message = _data_repo_status()
    if not ready:
        return False, status_message

    repo, branch, token = _data_settings()
    encoded_path = urllib.parse.quote(path, safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"

    _, sha, read_error = _github_read_bytes(path)
    if read_error:
        return False, read_error

    payload = {
        "message": message,
        "content": base64.b64encode(data).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **_github_headers(token),
            "Content-Type": "application/json",
        },
        method="PUT",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        return True, None
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message", "")
        except Exception:
            detail = ""
        suffix = f" — {detail}" if detail else ""
        return False, f"GitHub respondeu HTTP {exc.code} ao salvar {path}{suffix}."
    except Exception as exc:
        return False, f"Não foi possível salvar {path}: {exc}"


def _github_delete_path(path):
    ready, status_message = _data_repo_status()
    if not ready:
        return False, status_message

    repo, branch, token = _data_settings()
    encoded_path = urllib.parse.quote(path, safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
    _, sha, error = _github_read_bytes(path)
    if error:
        return False, error
    if not sha:
        return True, None

    payload = {
        "message": f"Remove pedido {path}",
        "sha": sha,
        "branch": branch,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **_github_headers(token),
            "Content-Type": "application/json",
        },
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
        return True, None
    except Exception as exc:
        return False, f"Não foi possível remover {path}: {exc}"


def _order_attachment_id(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()[:16]


def _json_header(header):
    out = {}
    for key, value in dict(header).items():
        if key in ("Proxima Compra", "Ciclo Meses"):
            continue
        if isinstance(value, (date, datetime, pd.Timestamp)):
            out[key] = value.isoformat()
        elif hasattr(value, "item"):
            try:
                out[key] = value.item()
            except Exception:
                out[key] = str(value)
        else:
            out[key] = value
    return out


def _serialize_order(order_data):
    items = order_data.get("items", pd.DataFrame())
    items_json = json.loads(
        items.to_json(orient="records", force_ascii=False)
    ) if isinstance(items, pd.DataFrame) else items

    return {
        "id": order_data["id"],
        "filename": order_data.get("filename", ""),
        "pdf_path": order_data.get(
            "pdf_path",
            f"orders/pdfs/{order_data['id']}.pdf",
        ),
        "header": _json_header(order_data.get("header", {})),
        "items": items_json,
        "not_parsed": list(order_data.get("not_parsed", [])),
    }


def _deserialize_order(payload):
    items = pd.DataFrame(payload.get("items", []))
    if not items.empty:
        items = update_receipt_columns(items)

    return {
        "id": str(payload.get("id", "")),
        "filename": str(payload.get("filename", "pedido.pdf")),
        "pdf_path": str(
            payload.get(
                "pdf_path",
                f"orders/pdfs/{payload.get('id', '')}.pdf",
            )
        ),
        "bytes": None,
        "header": dict(payload.get("header", {})),
        "items": items,
        "not_parsed": list(payload.get("not_parsed", [])),
        "extracted_text": "",
    }


def _load_persistent_orders():
    raw, _, error = _github_read_bytes(ORDERS_INDEX_PATH)
    if error:
        return {}, error
    if raw is None:
        return {}, None

    try:
        payload = json.loads(raw.decode("utf-8"))
        library = {}
        for saved in payload.get("orders", []):
            order_data = _deserialize_order(saved)
            if order_data["id"]:
                library[order_data["id"]] = order_data
        return library, None
    except Exception as exc:
        return {}, f"Não foi possível interpretar o histórico salvo: {exc}"


def _save_persistent_index(library):
    ready, message = _data_repo_status()
    if not ready:
        return False, message

    payload = {
        "version": 1,
        "orders": [
            _serialize_order(order_data)
            for order_data in library.values()
        ],
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    return _github_write_bytes(
        ORDERS_INDEX_PATH,
        raw,
        "Atualiza histórico de pedidos do NEXO",
    )


def _get_order_pdf_bytes(order_data):
    if order_data.get("bytes"):
        return order_data["bytes"], None

    pdf_path = order_data.get("pdf_path")
    if not pdf_path:
        return None, "PDF original não está disponível."

    raw, _, error = _github_read_bytes(pdf_path)
    if raw is not None:
        order_data["bytes"] = raw
    return raw, error


def _ensure_order_library():
    if "gestao_pedido_selecionado" not in st.session_state:
        st.session_state["gestao_pedido_selecionado"] = None
    if "gestao_fornecedor_selecionado" not in st.session_state:
        st.session_state["gestao_fornecedor_selecionado"] = None

    if "gestao_pedidos_loaded" not in st.session_state:
        ready, _ = _data_repo_status()
        if ready:
            library, error = _load_persistent_orders()
            st.session_state["gestao_pedidos_anexos"] = library
            st.session_state["gestao_pedidos_load_error"] = error or ""
        else:
            st.session_state.setdefault("gestao_pedidos_anexos", {})
            st.session_state["gestao_pedidos_load_error"] = ""
        st.session_state["gestao_pedidos_loaded"] = True

    return st.session_state.setdefault("gestao_pedidos_anexos", {})


def _add_order_attachments(uploaded_files):
    library = _ensure_order_library()
    added = 0
    errors = []
    ready, _ = _data_repo_status()
    added_ids = []

    for uploaded in uploaded_files or []:
        raw = uploaded.getvalue()
        attachment_id = _order_attachment_id(raw)

        if attachment_id in library:
            continue

        try:
            header, items, not_parsed, extracted_text = parse_order_pdf(raw)
            pdf_path = f"orders/pdfs/{attachment_id}.pdf"
            library[attachment_id] = {
                "id": attachment_id,
                "filename": uploaded.name,
                "pdf_path": pdf_path,
                "bytes": raw,
                "header": header,
                "items": items,
                "not_parsed": not_parsed,
                "extracted_text": extracted_text,
            }
            added += 1
            added_ids.append(attachment_id)

            if ready:
                ok, error = _github_write_bytes(
                    pdf_path,
                    raw,
                    f"Adiciona PDF do pedido {header.get('Pedido') or attachment_id}",
                )
                if not ok:
                    errors.append(f"{uploaded.name}: {error}")
        except Exception as exc:
            errors.append(f"{uploaded.name}: {exc}")

    if added and ready:
        ok, error = _save_persistent_index(library)
        if not ok:
            errors.append(error or "Não foi possível salvar o índice dos pedidos.")

    return added, errors


def _remove_order(library, order_id):
    order_data = library.get(order_id)
    if not order_data:
        return True, None

    ready, _ = _data_repo_status()
    pdf_path = order_data.get("pdf_path")

    library.pop(order_id, None)

    if ready:
        ok, error = _save_persistent_index(library)
        if not ok:
            return False, error
        if pdf_path:
            _github_delete_path(pdf_path)

    return True, None


def _supplier_key(header):
    code = str(header.get("Fornecedor Codigo") or "").strip().upper()
    if code:
        return code
    return re.sub(
        r"[^A-Z0-9]+",
        "",
        str(header.get("Fornecedor") or "").upper(),
    )


def _parse_order_date(value):
    try:
        return datetime.strptime(str(value), "%d/%m/%Y")
    except Exception:
        return None


def _orders_for_supplier(library, supplier_key):
    result = [
        order_data
        for order_data in library.values()
        if _supplier_key(order_data.get("header", {})) == supplier_key
    ]
    return sorted(
        result,
        key=lambda order: _parse_order_date(
            order.get("header", {}).get("Data Pedido", "")
        ) or datetime.min,
    )


def _find_previous_order(library, current_order):
    supplier_key = _supplier_key(current_order.get("header", {}))
    current_date = _parse_order_date(
        current_order.get("header", {}).get("Data Pedido", "")
    )
    if not supplier_key or current_date is None:
        return None

    candidates = []
    for order_data in _orders_for_supplier(library, supplier_key):
        if order_data["id"] == current_order["id"]:
            continue
        order_date = _parse_order_date(
            order_data.get("header", {}).get("Data Pedido", "")
        )
        if order_date and order_date < current_date:
            candidates.append(order_data)

    return candidates[-1] if candidates else None


def _item_key(row):
    code = re.sub(r"[^A-Z0-9]+", "", str(row.get("Codigo", "")).upper())
    if code:
        return "C:" + code
    reference = re.sub(
        r"[^A-Z0-9]+",
        "",
        str(row.get("Nr Fabricante", "")).upper(),
    )
    return "R:" + reference


def _compare_orders(previous_order, current_order):
    previous = previous_order["items"].copy()
    current = current_order["items"].copy()

    prev_map = {
        _item_key(row): row
        for row in previous.to_dict(orient="records")
    }
    curr_map = {
        _item_key(row): row
        for row in current.to_dict(orient="records")
    }

    rows = []
    for key in sorted(set(prev_map) | set(curr_map)):
        old = prev_map.get(key)
        new = curr_map.get(key)

        old_qty = float(old.get("Qtd Pedida", 0) or 0) if old else 0.0
        new_qty = float(new.get("Qtd Pedida", 0) or 0) if new else 0.0
        old_price = float(old.get("Vl Unitario", 0) or 0) if old else 0.0
        new_price = float(new.get("Vl Unitario", 0) or 0) if new else 0.0

        if old is None:
            situation = "NOVO"
        elif new is None:
            situation = "RETIRADO"
        elif new_qty > old_qty:
            situation = "AUMENTOU QTD"
        elif new_qty < old_qty:
            situation = "REDUZIU QTD"
        else:
            situation = "IGUAL"

        price_diff = new_price - old_price if old and new else 0.0
        price_pct = (
            (price_diff / old_price) * 100.0
            if old and new and old_price
            else None
        )

        base = new or old or {}
        rows.append(
            {
                "Codigo": base.get("Codigo", ""),
                "Nr Fabricante": base.get("Nr Fabricante", ""),
                "Descricao": base.get("Descricao", ""),
                "Qtd Anterior": old_qty if old else None,
                "Qtd Atual": new_qty if new else None,
                "Dif Qtd": (
                    new_qty - old_qty
                    if old and new
                    else (new_qty if new else -old_qty)
                ),
                "Preço Anterior": old_price if old else None,
                "Preço Atual": new_price if new else None,
                "Dif Preço R$": price_diff if old and new else None,
                "Dif Preço %": price_pct,
                "Situação": situation,
            }
        )

    return pd.DataFrame(rows)


def _pending_value(order_data):
    items = order_data.get("items", pd.DataFrame())
    if items.empty:
        return 0.0
    managed = update_receipt_columns(items)
    return float(
        (
            pd.to_numeric(managed["Qtd Pendente"], errors="coerce").fillna(0)
            * pd.to_numeric(managed["Vl Unitario"], errors="coerce").fillna(0)
        ).sum()
    )


def _purchase_alert(order_date, months):
    next_date = calculate_next_cycle(order_date, months)
    if next_date is None:
        return None, "Sem data para calcular", "info"

    today = date.today()
    delta = (next_date - today).days

    if delta < 0:
        return next_date, f"🔴 Compra atrasada há {abs(delta)} dia(s)", "error"
    if delta == 0:
        return next_date, "🔴 Compra prevista para hoje", "error"
    if next_date.year == today.year and next_date.month == today.month:
        return next_date, f"🟠 Compra este mês • faltam {delta} dia(s)", "warning"
    if delta <= 30:
        return next_date, f"🟠 Faltam {delta} dia(s)", "warning"
    return next_date, f"🟢 Faltam {delta} dia(s)", "success"


def _render_comparison(library, current_order):
    previous = _find_previous_order(library, current_order)
    if previous is None:
        st.info("Ainda não existe pedido anterior deste fornecedor para comparar.")
        return

    comparison = _compare_orders(previous, current_order)
    previous_header = previous.get("header", {})
    current_header = current_order.get("header", {})

    st.caption(
        f"Comparando pedido {current_header.get('Pedido') or 'atual'} com "
        f"{previous_header.get('Pedido') or 'pedido anterior'} de "
        f"{previous_header.get('Data Pedido') or 'data não identificada'}."
    )

    repeated = int(
        comparison["Situação"].isin(
            ["IGUAL", "AUMENTOU QTD", "REDUZIU QTD"]
        ).sum()
    )
    new_count = int((comparison["Situação"] == "NOVO").sum())
    removed_count = int((comparison["Situação"] == "RETIRADO").sum())
    price_up = int((pd.to_numeric(comparison["Dif Preço R$"], errors="coerce") > 0).sum())
    price_down = int((pd.to_numeric(comparison["Dif Preço R$"], errors="coerce") < 0).sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Itens repetidos", repeated)
    c2.metric("Itens novos", new_count)
    c3.metric("Retirados", removed_count)
    c4.metric("Preço aumentou", price_up)
    c5.metric("Preço reduziu", price_down)

    st.dataframe(
        comparison,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Preço Anterior": st.column_config.NumberColumn(format="R$ %.2f"),
            "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
            "Dif Preço R$": st.column_config.NumberColumn(format="R$ %.2f"),
            "Dif Preço %": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )


def _render_supplier_history(library, supplier_key, ciclo_meses):
    orders = _orders_for_supplier(library, supplier_key)
    if not orders:
        st.session_state["gestao_fornecedor_selecionado"] = None
        st.rerun()

    latest = orders[-1]
    header = latest.get("header", {})
    supplier_name = header.get("Fornecedor") or supplier_key

    top_left, top_right = st.columns([1, 5])
    with top_left:
        if st.button(
            "← Voltar",
            use_container_width=True,
            key=f"voltar_fornecedor_{supplier_key}",
        ):
            st.session_state["gestao_fornecedor_selecionado"] = None
            st.rerun()
    with top_right:
        st.markdown(f"## 🏭 {supplier_name}")

    total_value = sum(
        float(order.get("header", {}).get("Valor Pedido", 0) or 0)
        for order in orders
    )
    dates = [
        _parse_order_date(order.get("header", {}).get("Data Pedido", ""))
        for order in orders
    ]
    valid_dates = [d for d in dates if d is not None]
    intervals = [
        (valid_dates[i] - valid_dates[i - 1]).days
        for i in range(1, len(valid_dates))
    ]
    average_days = sum(intervals) / len(intervals) if intervals else None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pedidos", len(orders))
    m2.metric("Total comprado", money_br(total_value))
    m3.metric(
        "Último pedido",
        header.get("Data Pedido") or "—",
    )
    m4.metric(
        "Média entre compras",
        f"{average_days:.0f} dias" if average_days is not None else "—",
    )

    next_date, alert_text, level = _purchase_alert(
        header.get("Data Pedido", ""),
        int(ciclo_meses),
    )
    alert_message = (
        f"Próxima compra: {next_date.strftime('%d/%m/%Y')} • {alert_text}"
        if next_date
        else alert_text
    )
    if level == "error":
        st.error(alert_message)
    elif level == "warning":
        st.warning(alert_message)
    else:
        st.info(alert_message)

    history_rows = []
    for order in reversed(orders):
        h = order.get("header", {})
        history_rows.append(
            {
                "Pedido": h.get("Pedido", ""),
                "Data": h.get("Data Pedido", ""),
                "Valor": float(h.get("Valor Pedido", 0) or 0),
                "Itens": int(h.get("Itens", 0) or 0),
                "Qtd Total": float(h.get("Quantidade Total", 0) or 0),
            }
        )

    st.markdown("### Histórico de pedidos")
    st.dataframe(
        pd.DataFrame(history_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

    chart_rows = []
    for order in orders:
        h = order.get("header", {})
        dt = _parse_order_date(h.get("Data Pedido", ""))
        if dt:
            chart_rows.append(
                {
                    "Data": dt.date(),
                    "Valor do pedido": float(h.get("Valor Pedido", 0) or 0),
                }
            )
    if len(chart_rows) >= 2:
        st.markdown("### Evolução do valor das compras")
        chart_df = pd.DataFrame(chart_rows).set_index("Data")
        st.line_chart(chart_df)

    product_catalog = {}
    for order in orders:
        for row in order.get("items", pd.DataFrame()).to_dict(orient="records"):
            key = _item_key(row)
            label = (
                f"{row.get('Nr Fabricante', '')} • "
                f"{row.get('Descricao', '')}"
            ).strip(" •")
            product_catalog[key] = label or row.get("Codigo", key)

    if product_catalog:
        st.markdown("### Evolução de preço por produto")
        selected_product = st.selectbox(
            "Produto / referência",
            options=list(product_catalog.keys()),
            format_func=lambda key: product_catalog.get(key, key),
            key=f"historico_produto_{supplier_key}",
        )

        price_rows = []
        for order in orders:
            h = order.get("header", {})
            dt = _parse_order_date(h.get("Data Pedido", ""))
            for row in order.get("items", pd.DataFrame()).to_dict(orient="records"):
                if _item_key(row) == selected_product:
                    price_rows.append(
                        {
                            "Data": dt.date() if dt else h.get("Data Pedido", ""),
                            "Pedido": h.get("Pedido", ""),
                            "Preço": float(row.get("Vl Unitario", 0) or 0),
                            "Quantidade": float(row.get("Qtd Pedida", 0) or 0),
                        }
                    )

        price_df = pd.DataFrame(price_rows)
        if not price_df.empty:
            st.dataframe(
                price_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Preço": st.column_config.NumberColumn(format="R$ %.2f"),
                },
            )
            if len(price_df) >= 2:
                chart = price_df[["Data", "Preço"]].copy()
                chart["Data"] = pd.to_datetime(chart["Data"], errors="coerce")
                chart = chart.dropna(subset=["Data"]).set_index("Data")
                if not chart.empty:
                    st.line_chart(chart)


def _render_order_detail(order_data, ciclo_meses, library):
    header = dict(order_data["header"])
    items = order_data["items"].copy()
    not_parsed = order_data.get("not_parsed", [])

    header["Ciclo Meses"] = int(ciclo_meses)
    header["Proxima Compra"] = calculate_next_cycle(
        header.get("Data Pedido", ""),
        int(ciclo_meses),
    )

    top_left, top_right = st.columns([1, 5])
    with top_left:
        if st.button(
            "← Voltar",
            use_container_width=True,
            key=f"voltar_pedidos_{order_data['id']}",
        ):
            st.session_state["gestao_pedido_selecionado"] = None
            st.rerun()

    with top_right:
        st.caption(f"📎 Anexo: {order_data['filename']}")

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
        f"Próxima compra ({int(ciclo_meses)} {'mês' if int(ciclo_meses) == 1 else 'meses'})",
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

    _, alert_text, alert_level = _purchase_alert(
        header.get("Data Pedido", ""),
        int(ciclo_meses),
    )
    if alert_level == "error":
        st.error(alert_text)
    elif alert_level == "warning":
        st.warning(alert_text)
    else:
        st.caption(alert_text)

    pdf_total = float(header.get("Valor Pedido", 0) or 0)
    item_total = float(header.get("Valor Calculado Itens", 0) or 0)
    if pdf_total and abs(pdf_total - item_total) <= 0.02:
        st.success("✅ O valor somado dos itens confere com o valor total do PDF.")
    elif pdf_total:
        st.warning(
            "⚠️ O valor somado dos itens não confere com o total informado no PDF. "
            f"Diferença: {money_br(item_total - pdf_total)}."
        )

    with st.expander("🔄 Comparar com o pedido anterior", expanded=False):
        _render_comparison(library, order_data)

    st.markdown("### Itens do pedido")
    st.caption(
        "Você pode preencher a coluna **Qtd Recebida**. "
        "O saldo pendente e o status são recalculados logo abaixo."
    )

    editor_key = f"order_items_{order_data['id']}"
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
    library[order_data["id"]]["items"] = managed.copy()

    received_qty = float(managed["Qtd Recebida"].sum())
    pending_qty = float(managed["Qtd Pendente"].sum())
    received_items = int((managed["Status"] == "RECEBIDO").sum())
    partial_items = int((managed["Status"] == "PARCIAL").sum())

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Qtd recebida", f"{received_qty:,.0f}".replace(",", "."))
    r2.metric("Qtd pendente", f"{pending_qty:,.0f}".replace(",", "."))
    r3.metric("Itens recebidos", received_items)
    r4.metric("Itens parciais", partial_items)

    ready, _ = _data_repo_status()
    if ready:
        if st.button(
            "💾 Salvar acompanhamento permanentemente",
            key=f"save_receipt_{order_data['id']}",
        ):
            ok, error = _save_persistent_index(library)
            if ok:
                st.success("Acompanhamento salvo permanentemente.")
            else:
                st.error(error or "Não foi possível salvar.")

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
        key=f"export_order_xlsx_{order_data['id']}",
    )

    with st.expander("📄 Ver PDF anexado"):
        pdf_bytes, pdf_error = _get_order_pdf_bytes(order_data)
        if pdf_bytes:
            st.download_button(
                "📎 Baixar PDF original",
                data=pdf_bytes,
                file_name=order_data["filename"],
                mime="application/pdf",
                key=f"download_pdf_{order_data['id']}",
            )
        elif pdf_error:
            st.error(pdf_error)

    extracted_text = order_data.get("extracted_text", "")
    if extracted_text:
        with st.expander("🔧 Diagnóstico da leitura do PDF"):
            st.caption(
                "Use esta área apenas se algum dado não for reconhecido corretamente."
            )
            st.text_area(
                "Texto extraído",
                extracted_text,
                height=220,
                disabled=True,
                key=f"order_extracted_text_{order_data['id']}",
            )


def render_gestao_pedidos():
    st.title("🧾 Gestão de Pedidos")
    st.caption(
        "Centralize seus pedidos em PDF, acompanhe o histórico e compare automaticamente as compras."
    )

    library = _ensure_order_library()
    persistence_ready, persistence_message = _data_repo_status()

    with st.sidebar:
        st.markdown("---")
        st.markdown("### Gestão de Pedidos")
        ciclo_meses = st.number_input(
            "Intervalo entre compras (meses)",
            min_value=1,
            max_value=24,
            value=2,
            step=1,
            key="gestao_ciclo_meses",
            help=(
                "Define quantos meses após a data do pedido o NEXO deve indicar "
                "como próxima compra."
            ),
        )
        st.caption(
            f"Próxima compra será projetada {int(ciclo_meses)} "
            f"{'mês' if int(ciclo_meses) == 1 else 'meses'} após cada pedido."
        )
        if persistence_ready:
            st.success("☁️ Pedidos permanentes habilitados")
        else:
            st.warning("⚠️ Pedidos ainda ficam somente na sessão")
            with st.expander("Como ativar o salvamento permanente"):
                st.caption(
                    "Use um repositório PRIVADO separado para os PDFs e dados dos pedidos. "
                    "Depois configure GITHUB_DATA_REPO nos Secrets do Streamlit."
                )

    load_error = st.session_state.get("gestao_pedidos_load_error", "")
    if load_error:
        st.warning(load_error)

    selected_supplier = st.session_state.get("gestao_fornecedor_selecionado")
    if selected_supplier:
        _render_supplier_history(library, selected_supplier, ciclo_meses)
        return

    selected_id = st.session_state.get("gestao_pedido_selecionado")
    if selected_id and selected_id in library:
        _render_order_detail(library[selected_id], ciclo_meses, library)
        return
    elif selected_id:
        st.session_state["gestao_pedido_selecionado"] = None

    st.markdown("### Pedidos anexados")

    upload_flash = st.session_state.pop("gestao_upload_flash", "")
    if upload_flash:
        st.success(upload_flash)

    upload_errors = st.session_state.pop("gestao_upload_errors", [])
    for error in upload_errors:
        st.error(error)

    with st.expander("➕ Anexar pedido(s) em PDF", expanded=not bool(library)):
        st.caption(
            "Você pode selecionar vários PDFs de uma vez. Cada arquivo será transformado em um pedido."
        )
        upload_version = int(st.session_state.get("gestao_upload_version", 0))
        uploaded_files = st.file_uploader(
            "Selecionar Pedido(s) Fornecedor em PDF",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"gestao_pedidos_pdf_multiplos_{upload_version}",
            help="Use os PDFs originais gerados pelo sistema.",
        )

        if uploaded_files:
            added, errors = _add_order_attachments(uploaded_files)

            if added:
                if persistence_ready:
                    st.session_state["gestao_upload_flash"] = (
                        f"{added} pedido(s) adicionado(s) e salvo(s) permanentemente."
                    )
                else:
                    st.session_state["gestao_upload_flash"] = (
                        f"{added} pedido(s) adicionado(s) à sessão."
                    )

                if errors:
                    st.session_state["gestao_upload_errors"] = errors

                # Troca a chave do file_uploader para limpar os arquivos
                # já processados sem afetar os pedidos salvos.
                st.session_state["gestao_upload_version"] = upload_version + 1
                st.rerun()

            for error in errors:
                st.error(error)

    if not library:
        st.info("Ainda não há pedidos anexados. Use a opção acima para adicionar o primeiro PDF.")
        return

    search = st.text_input(
        "Buscar pedido ou fornecedor",
        key="gestao_busca_pedidos",
        placeholder="Ex.: 7432 ou VALCLEI",
    ).strip().lower()

    records = []
    for attachment_id, order_data in library.items():
        header = order_data["header"]
        records.append(
            {
                "id": attachment_id,
                "pedido": str(header.get("Pedido") or ""),
                "fornecedor": str(header.get("Fornecedor") or ""),
                "fornecedor_key": _supplier_key(header),
                "data": str(header.get("Data Pedido") or ""),
                "valor": float(header.get("Valor Pedido", 0) or 0),
                "itens": int(header.get("Itens", 0) or 0),
                "filename": order_data["filename"],
            }
        )

    def date_sort_value(record):
        try:
            return datetime.strptime(record["data"], "%d/%m/%Y")
        except Exception:
            return datetime.min

    records.sort(key=date_sort_value, reverse=True)

    if search:
        records = [
            rec for rec in records
            if search in rec["pedido"].lower()
            or search in rec["fornecedor"].lower()
            or search in rec["filename"].lower()
        ]

    total_value = sum(rec["valor"] for rec in records)
    total_items = sum(rec["itens"] for rec in records)
    suppliers_count = len(
        {rec["fornecedor_key"] for rec in records if rec["fornecedor_key"]}
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Pedidos anexados", len(records))
    k2.metric("Fornecedores", suppliers_count)
    k3.metric("Itens comprados", total_items)
    k4.metric("Valor comprado", money_br(total_value))

    if not records:
        st.warning("Nenhum pedido encontrado para essa busca.")
        return

    meses_pt = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
    }

    grupos = {}
    for rec in records:
        try:
            dt = datetime.strptime(rec["data"], "%d/%m/%Y")
            chave = (dt.year, dt.month)
            titulo_mes = f"{meses_pt[dt.month]} {dt.year}"
        except Exception:
            chave = (0, 0)
            titulo_mes = "SEM DATA"

        grupos.setdefault(
            chave,
            {"titulo": titulo_mes, "pedidos": []},
        )["pedidos"].append(rec)

    grupos_ordenados = sorted(
        grupos.items(),
        key=lambda item: item[0],
        reverse=True,
    )

    for indice_grupo, (_, grupo) in enumerate(grupos_ordenados):
        pedidos_mes = grupo["pedidos"]
        valor_mes = sum(rec["valor"] for rec in pedidos_mes)
        qtd_mes = len(pedidos_mes)
        fornecedores_mes = len(
            {rec["fornecedor_key"] for rec in pedidos_mes if rec["fornecedor_key"]}
        )
        itens_mes = sum(rec["itens"] for rec in pedidos_mes)

        titulo_expander = (
            f"📅 {grupo['titulo']}  •  "
            f"{qtd_mes} {'pedido' if qtd_mes == 1 else 'pedidos'}  •  "
            f"{money_br(valor_mes)}"
        )

        with st.expander(
            titulo_expander,
            expanded=(indice_grupo == 0),
        ):
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Pedidos", qtd_mes)
            m2.metric("Fornecedores", fornecedores_mes)
            m3.metric("Itens", itens_mes)
            m4.metric("Comprado", money_br(valor_mes))

            for rec in pedidos_mes:
                with st.container(border=True):
                    col_main, col_meta, col_actions = st.columns([3.2, 2, 1.3])

                    with col_main:
                        st.markdown(f"### 📎 Pedido {rec['pedido'] or 'sem número'}")
                        if st.button(
                            f"🏭 {rec['fornecedor'] or 'Fornecedor não identificado'}",
                            key=f"historico_fornecedor_{rec['id']}",
                        ):
                            st.session_state["gestao_fornecedor_selecionado"] = rec["fornecedor_key"]
                            st.rerun()
                        st.caption(rec["filename"])

                    with col_meta:
                        st.markdown(f"**Data:** {rec['data'] or '—'}")
                        st.markdown(f"**Valor:** {money_br(rec['valor'])}")
                        st.markdown(f"**Itens:** {rec['itens']}")

                        supplier_orders = _orders_for_supplier(
                            library,
                            rec["fornecedor_key"],
                        )
                        if supplier_orders and supplier_orders[-1]["id"] == rec["id"]:
                            next_date, alert_text, _ = _purchase_alert(
                                rec["data"],
                                int(ciclo_meses),
                            )
                            if next_date:
                                st.caption(
                                    f"Próxima: {next_date.strftime('%d/%m/%Y')} • {alert_text}"
                                )

                    with col_actions:
                        if st.button(
                            "Abrir pedido",
                            use_container_width=True,
                            type="primary",
                            key=f"abrir_pedido_{rec['id']}",
                        ):
                            st.session_state["gestao_pedido_selecionado"] = rec["id"]
                            st.rerun()

                        delete_key = f"confirmar_exclusao_{rec['id']}"
                        confirm_delete = bool(
                            st.session_state.get(delete_key, False)
                        )

                        if not confirm_delete:
                            if st.button(
                                "Remover",
                                use_container_width=True,
                                key=f"remover_pedido_{rec['id']}",
                            ):
                                st.session_state[delete_key] = True
                                st.rerun()
                        else:
                            st.warning(
                                f"Excluir permanentemente o pedido "
                                f"{rec['pedido'] or 'sem número'}?"
                            )

                            if st.button(
                                "Excluir permanentemente",
                                use_container_width=True,
                                type="primary",
                                key=f"confirmar_remocao_{rec['id']}",
                            ):
                                ok, error = _remove_order(
                                    library,
                                    rec["id"],
                                )
                                if not ok and error:
                                    st.error(error)
                                else:
                                    st.session_state.pop(
                                        delete_key,
                                        None,
                                    )
                                    st.rerun()

                            if st.button(
                                "Cancelar",
                                use_container_width=True,
                                key=f"cancelar_remocao_{rec['id']}",
                            ):
                                st.session_state.pop(delete_key, None)
                                st.rerun()

    if persistence_ready:
        st.caption(
            "☁️ PDFs e histórico estão sendo guardados no repositório privado de dados."
        )
    else:
        st.caption(
            "⚠️ Nesta configuração os pedidos ficam somente durante a sessão. "
            "O NEXO não grava PDFs no repositório público do aplicativo."
        )


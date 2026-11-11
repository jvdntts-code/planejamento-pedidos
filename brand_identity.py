"""Identificação auditável da marca presente nos produtos importados.

Nunca deduzir a marca pelo nome do arquivo nem pelo código da linha.
"""
import re
import unicodedata

import pandas as pd


def _key(value):
    if pd.isna(value):
        return ""
    return re.sub(r"[^A-Z0-9]+", "", re.sub(r"\.0$", "", str(value).strip().upper()))


def _field(df, *names):
    def normal(value):
        return "".join(
            c for c in unicodedata.normalize("NFKD", str(value)).upper()
            if c.isalnum() and not unicodedata.combining(c)
        )
    mapping = {normal(c): c for c in df.columns}
    for name in names:
        if normal(name) in mapping:
            return mapping[normal(name)]
    return None


def _brands_by_code(df, label):
    """Mapa código -> marca. Bloqueia marcas conflitantes no mesmo código."""
    if df is None or df.empty:
        return {}
    brand_col = _field(df, "Marca")
    code_col = _field(df, "Codigo", "Código", "CodProduto", "Código interno")
    if brand_col is None or code_col is None:
        return {}
    keyed = pd.DataFrame({
        "code": df[code_col].map(_key),
        "brand": df[brand_col].fillna("").astype(str).str.strip().str.upper(),
    })
    keyed = keyed[
        keyed["code"].ne("") & keyed["brand"].ne("")
        & ~keyed["brand"].isin(["NAN", "NONE", "NULL", "NÃO INFORMADA", "NAO INFORMADA"])
    ]
    if keyed.empty:
        return {}
    unique = keyed.groupby("code")["brand"].nunique()
    if (unique > 1).any():
        raise ValueError(
            f"O arquivo {label} atribui marcas diferentes ao mesmo código. "
            "Corrija a origem antes de analisar."
        )
    return keyed.drop_duplicates("code").set_index("code")["brand"].to_dict()


def identify_brand(base, raw, sales=None):
    """Retorna (marca, códigos identificados, total, origem). Não mistura marcas."""
    if "codigo" not in base.columns:
        raise ValueError("Base sem código interno do produto.")
    raw_map = _brands_by_code(raw, "Lista de Produtos por Marca")
    sales_map = _brands_by_code(sales, "Vendas Produtos")
    codes = base["codigo"].map(_key)
    resolved = []
    used_sales = False
    used_raw = False
    for code in codes:
        a, b = raw_map.get(code), sales_map.get(code)
        if a and b and a != b:
            raise ValueError(
                f"Marca divergente entre relatórios para o código {code}: {a} e {b}."
            )
        resolved.append(a or b or "")
        used_raw |= bool(a)
        used_sales |= bool(b)
    distinct = sorted({label for label in resolved if label})
    if len(distinct) > 1:
        raise ValueError(
            "Os relatórios contêm mais de uma marca nos produtos analisados ("
            + ", ".join(distinct[:8])
            + "). Importe relatórios filtrados para uma única marca."
        )
    source = (
        "Lista de Produtos por Marca e Vendas Produtos" if used_raw and used_sales
        else "Lista de Produtos por Marca" if used_raw
        else "Vendas Produtos" if used_sales
        else "Não identificada nos relatórios"
    )
    return distinct[0] if distinct else None, sum(bool(x) for x in resolved), len(resolved), source

import base64
import gzip
import hashlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request
import unicodedata

import pandas as pd
import streamlit as st

from auth_module import current_username, user_storage_prefix


COLUNAS = [
    "brand", "store", "year", "month", "product_code", "description",
    "reference", "quantity", "revenue", "company", "category", "source_file",
]
MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
PERIODICIDADES = ["Mensal", "Trimestral", "Semestral", "Anual"]


def _secret(nome, padrao=""):
    try:
        return st.secrets[nome] if nome in st.secrets else padrao
    except Exception:
        return padrao


def _configuracao():
    # Os dados operacionais devem ficar exclusivamente no repositório privado.
    repo = str(_secret("GITHUB_DATA_REPO", "")).strip()
    branch = str(_secret("GITHUB_DATA_BRANCH", _secret("GITHUB_BRANCH", "main"))).strip() or "main"
    token = str(_secret("GITHUB_TOKEN", "")).strip()
    return repo, branch, token


def _caminho_dados():
    return f"{user_storage_prefix()}/sellout/base.csv.gz"


def _cabecalhos(token):
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nexo-sellout",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }


def _vazio():
    return pd.DataFrame(columns=COLUNAS)


def _normalizar_base(df):
    if df is None or df.empty:
        return _vazio()
    df = df.copy()
    for coluna in COLUNAS:
        if coluna not in df.columns:
            df[coluna] = "" if coluna in {
                "brand", "store", "product_code", "description",
                "reference", "company", "category", "source_file",
            } else 0
    df = df[COLUNAS]
    textos = [
        "brand", "store", "product_code", "description",
        "reference", "company", "category", "source_file",
    ]
    for coluna in textos:
        df[coluna] = df[coluna].fillna("").astype(str).str.strip()
    for coluna in ["year", "month"]:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").fillna(0).astype(int)
    for coluna in ["quantity", "revenue"]:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").fillna(0.0).astype(float)
    df["store"] = df["store"].str.upper()
    return df


def _carregar_remoto():
    repo, branch, token = _configuracao()
    if not repo or not token:
        return _vazio(), ""
    caminho = urllib.parse.quote(_caminho_dados(), safe="/")
    url = (
        f"https://api.github.com/repos/{repo}/contents/{caminho}"
        f"?ref={urllib.parse.quote(branch, safe='')}"
    )
    try:
        req = urllib.request.Request(url, headers=_cabecalhos(token))
        with urllib.request.urlopen(req, timeout=20) as resposta:
            payload = json.loads(resposta.read().decode("utf-8"))
        conteudo = base64.b64decode(payload.get("content", ""))
        bruto = gzip.decompress(conteudo)
        base = pd.read_csv(
            io.BytesIO(bruto),
            dtype={"store": str, "product_code": str},
        )
        return _normalizar_base(base), ""
    except urllib.error.HTTPError as erro:
        if erro.code == 404:
            return _vazio(), ""
        return _vazio(), f"Não foi possível carregar a base privada (HTTP {erro.code})."
    except Exception:
        return _vazio(), "Não foi possível carregar a base consolidada. Confira a configuração de acesso ao repositório privado."


def _salvar_remoto(df):
    repo, branch, token = _configuracao()
    if not repo or not token:
        return False, "Configure GITHUB_DATA_REPO e GITHUB_TOKEN nos Secrets do Streamlit para salvar a base de forma permanente."
    conteudo = gzip.compress(
        _normalizar_base(df).to_csv(index=False, lineterminator="\n").encode("utf-8"),
        compresslevel=6,
        mtime=0,
    )
    caminho = urllib.parse.quote(_caminho_dados(), safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{caminho}"
    sha = None
    try:
        consulta = urllib.request.Request(
            url + f"?ref={urllib.parse.quote(branch, safe='')}",
            headers=_cabecalhos(token),
        )
        with urllib.request.urlopen(consulta, timeout=20) as resposta:
            sha = json.loads(resposta.read().decode("utf-8")).get("sha")
    except urllib.error.HTTPError as erro:
        if erro.code != 404:
            return False, f"Falha ao preparar o salvamento da base (HTTP {erro.code})."
    except Exception:
        return False, "Falha ao preparar o salvamento da base privada."

    corpo = {
        "message": "Atualiza base consolidada de Sell-out do NEXO",
        "content": base64.b64encode(conteudo).decode("ascii"),
        "branch": branch,
    }
    if sha:
        corpo["sha"] = sha
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={**_cabecalhos(token), "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=30):
            return True, "Base consolidada salva no repositório privado da conta."
    except urllib.error.HTTPError as erro:
        return False, f"Falha ao salvar a base privada (HTTP {erro.code})."
    except Exception:
        return False, "Falha ao salvar a base privada. Os dados continuam disponíveis nesta sessão."


def _carregar():
    usuario = current_username()
    if (
        not st.session_state.get("sellout_carregado")
        or st.session_state.get("sellout_usuario") != usuario
    ):
        base, erro = _carregar_remoto()
        st.session_state["sellout_base"] = base
        st.session_state["sellout_erro"] = erro
        st.session_state["sellout_carregado"] = True
        st.session_state["sellout_usuario"] = usuario
    return _normalizar_base(st.session_state.get("sellout_base", _vazio()))


def _persistir(df):
    df = _normalizar_base(df)
    st.session_state["sellout_base"] = df
    ok, mensagem = _salvar_remoto(df)
    st.session_state["sellout_feedback"] = mensagem
    return ok


def _normalizar_texto(valor):
    texto = str(valor or "").lower().strip()
    texto = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    return "".join(caractere for caractere in texto if caractere.isalnum())


def _coluna(df, aliases):
    colunas = {_normalizar_texto(coluna): coluna for coluna in df.columns}
    for alias in aliases:
        chave = _normalizar_texto(alias)
        if chave in colunas:
            return colunas[chave]
    return None


def _identificador(valor):
    if pd.isna(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    texto = str(valor).strip()
    return texto[:-2] if texto.endswith(".0") else texto


def _numero(valor):
    if pd.isna(valor):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).replace("R$", "").replace(" ", "").strip()
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except (TypeError, ValueError):
        return 0.0


def _ler_arquivo(arquivo):
    bruto = arquivo.getvalue()
    nome = arquivo.name.lower()
    if nome.endswith(".csv"):
        ultimo_erro = None
        for codificacao in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                return [
                    pd.read_csv(
                        io.BytesIO(bruto),
                        sep=None,
                        engine="python",
                        encoding=codificacao,
                    )
                ]
            except Exception as erro:
                ultimo_erro = erro
        raise ValueError(f"CSV inválido: {ultimo_erro}")
    if nome.endswith((".xlsx", ".xls")):
        planilhas = pd.read_excel(io.BytesIO(bruto), sheet_name=None)
        return [df for df in planilhas.values() if df is not None and not df.empty]
    raise ValueError("Formato não reconhecido. Use XLSX, XLS ou CSV.")


def _padronizar(df, marca, nome_arquivo):
    aliases = {
        "store": ["loja__", "loja", "filial", "store", "codigo loja"],
        "month": ["mes___", "mes", "month"],
        "year": ["ano___", "ano", "year"],
        "product_code": ["codigo", "codigo produto", "codigo interno", "sku"],
        "description": ["descri", "descricao", "descricao produto", "produto"],
        "reference": ["refere", "referencia", "ref fabricante"],
        "quantity": ["quanti", "quantidade", "qtd", "unidades"],
        "revenue": ["total_", "total", "faturamento", "valor total", "valor venda"],
        "company": ["empresa", "company"],
        "category": ["categoria", "category", "grupo produto"],
    }
    colunas = {campo: _coluna(df, nomes) for campo, nomes in aliases.items()}
    obrigatorias = ["store", "month", "year", "product_code", "quantity", "revenue"]
    faltantes = [campo for campo in obrigatorias if colunas[campo] is None]
    if faltantes:
        nomes = {
            "store": "loja", "month": "mês", "year": "ano",
            "product_code": "código do produto", "quantity": "quantidade",
            "revenue": "faturamento/total",
        }
        raise ValueError(
            "Colunas obrigatórias ausentes: "
            + ", ".join(nomes[campo] for campo in faltantes)
        )

    tamanho = len(df)
    saida = pd.DataFrame(index=df.index)
    saida["brand"] = str(marca).strip() or "VOX"
    saida["store"] = df[colunas["store"]].map(_identificador).str.upper()
    saida["year"] = pd.to_numeric(df[colunas["year"]], errors="coerce")
    saida["month"] = pd.to_numeric(df[colunas["month"]], errors="coerce")
    saida["product_code"] = df[colunas["product_code"]].map(_identificador)
    saida["description"] = (
        df[colunas["description"]].fillna("").astype(str).str.strip()
        if colunas["description"] else ""
    )
    saida["reference"] = (
        df[colunas["reference"]].map(_identificador)
        if colunas["reference"] else ""
    )
    saida["quantity"] = df[colunas["quantity"]].map(_numero)
    saida["revenue"] = df[colunas["revenue"]].map(_numero)
    saida["company"] = (
        df[colunas["company"]].map(_identificador)
        if colunas["company"] else ""
    )
    saida["category"] = (
        df[colunas["category"]].fillna("").astype(str).str.strip()
        if colunas["category"] else ""
    )
    saida["source_file"] = nome_arquivo

    saida = saida[
        saida["store"].ne("")
        & saida["product_code"].ne("")
        & saida["year"].notna()
        & saida["month"].notna()
    ].copy()
    saida["year"] = saida["year"].astype(int)
    saida["month"] = saida["month"].astype(int)
    saida = saida[
        saida["month"].between(1, 12)
        & saida["year"].between(2000, 2100)
    ].copy()
    if saida.empty:
        raise ValueError("Nenhuma linha válida após conferir loja, mês, ano e código.")
    return _normalizar_base(saida)


def _importar(arquivos, marca):
    quadros, erros, hashes_vistos, repetidos = [], [], set(), []
    for arquivo in arquivos:
        digest = hashlib.sha256(arquivo.getvalue()).hexdigest()
        if digest in hashes_vistos:
            repetidos.append(arquivo.name)
            continue
        hashes_vistos.add(digest)
        validos, erros_planilha = [], []
        try:
            for planilha in _ler_arquivo(arquivo):
                try:
                    validos.append(_padronizar(planilha, marca, arquivo.name))
                except Exception as erro:
                    erros_planilha.append(str(erro))
            if validos:
                quadros.extend(validos)
            else:
                detalhe = erros_planilha[0] if erros_planilha else "arquivo sem dados"
                erros.append(f"{arquivo.name}: {detalhe}")
        except Exception as erro:
            erros.append(f"{arquivo.name}: {erro}")
    if erros:
        return None, erros, repetidos
    if not quadros:
        return None, ["Nenhuma linha válida encontrada."], repetidos
    return _normalizar_base(pd.concat(quadros, ignore_index=True)), [], repetidos


def _meses(periodicidade, escolha):
    if periodicidade == "Mensal":
        return [tuple(escolha)]
    if periodicidade == "Trimestral":
        ano, trimestre = escolha
        inicio = (trimestre - 1) * 3 + 1
        return [(ano, mes) for mes in range(inicio, inicio + 3)]
    if periodicidade == "Semestral":
        ano, semestre = escolha
        inicio = 1 if semestre == 1 else 7
        return [(ano, mes) for mes in range(inicio, inicio + 6)]
    return [(int(escolha), mes) for mes in range(1, 13)]


def _comparacao_anterior(periodicidade, escolha, metodo):
    if periodicidade == "Mensal":
        ano, mes = escolha
        if metodo == "Mesmo período do ano anterior":
            return [(ano - 1, mes)]
        return [(ano - 1, 12)] if mes == 1 else [(ano, mes - 1)]
    if periodicidade == "Trimestral":
        ano, trimestre = escolha
        if metodo == "Mesmo período do ano anterior":
            return _meses(periodicidade, (ano - 1, trimestre))
        return _meses(periodicidade, (ano - 1, 4)) if trimestre == 1 else _meses(periodicidade, (ano, trimestre - 1))
    if periodicidade == "Semestral":
        ano, semestre = escolha
        if metodo == "Mesmo período do ano anterior":
            return _meses(periodicidade, (ano - 1, semestre))
        return _meses(periodicidade, (ano - 1, 2)) if semestre == 1 else _meses(periodicidade, (ano, 1))
    return _meses("Anual", int(escolha) - 1)


def _rotulo(periodicidade, escolha):
    if periodicidade == "Mensal":
        ano, mes = escolha
        return f"{MESES[int(mes) - 1]}/{int(ano)}"
    if periodicidade == "Trimestral":
        return f"{escolha[1]}º trimestre/{escolha[0]}"
    if periodicidade == "Semestral":
        return f"{escolha[1]}º semestre/{escolha[0]}"
    return f"Ano {escolha}"


def _rotulo_base(periodicidade, meses):
    ano, mes = meses[0]
    if periodicidade == "Mensal":
        return _rotulo(periodicidade, (ano, mes))
    if periodicidade == "Trimestral":
        return f"{(mes - 1) // 3 + 1}º trimestre/{ano}"
    if periodicidade == "Semestral":
        return f"{1 if mes <= 6 else 2}º semestre/{ano}"
    return f"Ano {ano}"


def _filtrar_periodo(df, meses):
    if df.empty or not meses:
        return df.iloc[0:0].copy()
    pares = pd.Series(
        list(zip(df["year"].astype(int), df["month"].astype(int))),
        index=df.index,
    )
    return df.loc[pares.isin(set(meses))].copy()


def _meses_comparaveis(df, meses_atuais, meses_anteriores):
    disponiveis = set(zip(df["year"].astype(int), df["month"].astype(int)))
    pares = [
        (atual, anterior)
        for atual, anterior in zip(meses_atuais, meses_anteriores)
        if atual in disponiveis and anterior in disponiveis
    ]
    return (
        _filtrar_periodo(df, [atual for atual, _ in pares]),
        _filtrar_periodo(df, [anterior for _, anterior in pares]),
        len(pares),
    )


def _opcoes_periodo(df, periodicidade):
    chaves = sorted(
        set(zip(df["year"].astype(int), df["month"].astype(int))),
        reverse=True,
    )
    if periodicidade == "Mensal":
        return chaves
    if periodicidade == "Trimestral":
        return sorted({(ano, (mes - 1) // 3 + 1) for ano, mes in chaves}, reverse=True)
    if periodicidade == "Semestral":
        return sorted({(ano, 1 if mes <= 6 else 2) for ano, mes in chaves}, reverse=True)
    return sorted({ano for ano, _ in chaves}, reverse=True)


def _resumo(df):
    faturamento = float(df["revenue"].sum())
    unidades = float(df["quantity"].sum())
    return {
        "revenue": faturamento,
        "quantity": unidades,
        "average": faturamento / unidades if unidades else 0.0,
        "records": len(df),
        "skus": df["product_code"].nunique(),
        "stores": df["store"].nunique(),
    }


def _variacao(atual, anterior):
    return None if anterior == 0 else (atual / anterior - 1) * 100


def _moeda(valor):
    valor = float(valor or 0)
    formatado = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {formatado}" if valor < 0 else f"R$ {formatado}"


def _agregar(df, chave):
    if df.empty:
        return pd.DataFrame(columns=[chave, "quantity", "revenue"])
    if chave == "product_code":
        def valor_mais_frequente(serie):
            valores = serie.fillna("").astype(str).str.strip()
            valores = valores[valores.ne("")]
            if valores.empty:
                return ""
            return valores.value_counts().index[0]

        return df.groupby(chave, as_index=False).agg(
            reference=("reference", valor_mais_frequente),
            description=("description", valor_mais_frequente),
            quantity=("quantity", "sum"),
            revenue=("revenue", "sum"),
        )
    return df.groupby(chave, as_index=False).agg(
        quantity=("quantity", "sum"),
        revenue=("revenue", "sum"),
    )


def _comparar(atual, anterior, chave, total_atual, total_anterior):
    resultado = atual.merge(anterior, on=chave, how="outer", suffixes=("_atual", "_base"))
    for coluna in ["quantity_atual", "quantity_base", "revenue_atual", "revenue_base"]:
        resultado[coluna] = pd.to_numeric(resultado[coluna], errors="coerce").fillna(0.0)
    if chave == "product_code":
        for coluna in ["reference", "description"]:
            resultado[coluna] = (
                resultado[f"{coluna}_atual"].fillna("").replace("", pd.NA)
                .fillna(resultado[f"{coluna}_base"]).fillna("")
            )
    resultado["delta_revenue"] = resultado["revenue_atual"] - resultado["revenue_base"]
    resultado["delta_pct"] = resultado.apply(
        lambda linha: _variacao(linha["revenue_atual"], linha["revenue_base"]),
        axis=1,
    )
    resultado["share_atual"] = (
        resultado["revenue_atual"] / total_atual * 100 if total_atual else 0
    )
    resultado["share_base"] = (
        resultado["revenue_base"] / total_anterior * 100 if total_anterior else 0
    )
    resultado["share_delta"] = resultado["share_atual"] - resultado["share_base"]
    resultado["status"] = "Mantido"
    resultado.loc[
        (resultado["revenue_base"] == 0) & (resultado["revenue_atual"] > 0),
        "status",
    ] = "Novo no período"
    resultado.loc[
        (resultado["revenue_atual"] == 0) & (resultado["revenue_base"] > 0),
        "status",
    ] = "Sem venda no período"
    return resultado


def _exportar(resumo, produtos, lojas, periodo_atual, periodo_base):
    arquivo = io.BytesIO()
    with pd.ExcelWriter(arquivo, engine="openpyxl") as escritor:
        pd.DataFrame(resumo).to_excel(escritor, sheet_name="Resumo", index=False)
        produtos.to_excel(escritor, sheet_name="Produtos", index=False)
        lojas.to_excel(escritor, sheet_name="Lojas", index=False)
        periodo_atual.to_excel(escritor, sheet_name="Base período", index=False)
        periodo_base.to_excel(escritor, sheet_name="Base comparação", index=False)
        for planilha in escritor.book.worksheets:
            planilha.freeze_panes = "A2"
            planilha.auto_filter.ref = planilha.dimensions
            for coluna in planilha.columns:
                largura = max(len(str(celula.value or "")) for celula in coluna[:250]) + 2
                planilha.column_dimensions[coluna[0].column_letter].width = min(max(largura, 11), 38)
    return arquivo.getvalue()


def render_sellout():
    base = _carregar()
    st.title("Análise de Sell-out")
    st.caption("Desempenho comercial por período, produto e loja, com consolidação dos relatórios importados.")

    erro = st.session_state.pop("sellout_erro", "")
    if erro:
        st.warning(erro)
    feedback = st.session_state.pop("sellout_feedback", "")
    if feedback:
        if "salva" in feedback.lower():
            st.success(feedback)
        else:
            st.warning(feedback)

    repo, _, token = _configuracao()
    if not repo or not token:
        st.info(
            "A base fica disponível apenas nesta sessão até configurar "
            "GITHUB_DATA_REPO e GITHUB_TOKEN nos Secrets do Streamlit."
        )

    with st.expander("Importar ou atualizar relatórios", expanded=base.empty):
        st.caption(
            "Envie um ou vários relatórios XLSX, XLS ou CSV. Os arquivos são consolidados "
            "automaticamente. Ao importar novamente uma marca e um mês já existentes, "
            "os dados daquele mês são substituídos para evitar duplicidade."
        )
        marca = st.text_input("Marca analisada", value="VOX", key="sellout_marca_importacao")
        versao = int(st.session_state.get("sellout_versao_upload", 0))
        arquivos = st.file_uploader(
            "Relatórios mensais",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=True,
            key=f"sellout_arquivos_{versao}",
        )
        if st.button(
            "Processar e consolidar arquivos",
            type="primary",
            use_container_width=True,
            key="sellout_processar",
        ):
            if not arquivos:
                st.warning("Selecione pelo menos um arquivo.")
            elif not marca.strip():
                st.warning("Informe a marca analisada.")
            else:
                novos, erros, repetidos = _importar(arquivos, marca)
                if erros:
                    for mensagem in erros:
                        st.error(mensagem)
                else:
                    meses_importados = sorted(
                        {_rotulo("Mensal", (ano, mes)) for ano, mes in set(zip(novos.year, novos.month))}
                    )
                    _persistir(_mesclar(base, novos))
                    st.session_state["sellout_versao_upload"] = versao + 1
                    st.session_state["sellout_aviso_importacao"] = (
                        f"{len(novos):,} registros processados. Meses atualizados: "
                        + ", ".join(meses_importados)
                        + (" Arquivos repetidos foram ignorados." if repetidos else "")
                    )
                    st.rerun()

    aviso = st.session_state.pop("sellout_aviso_importacao", "")
    if aviso:
        st.success(aviso)
        base = _carregar()
    if base.empty:
        st.info("Importe os relatórios mensais para iniciar. A base é privada e separada por conta do NEXO.")
        return

    marcas = sorted(base["brand"].replace("", "VOX").unique())
    marca = st.selectbox("Marca", marcas, key="sellout_marca_selecionada") if len(marcas) > 1 else marcas[0]
    df = base[base["brand"].eq(marca)].copy()
    meses_disponiveis = set(zip(df["year"].astype(int), df["month"].astype(int)))
    st.caption(
        f"Base consolidada: {len(df):,} registros · {df.product_code.nunique():,} SKUs · "
        f"{df.store.nunique():,} lojas · {len(meses_disponiveis)} mês(es) com dados."
    )

    c1, c2, c3 = st.columns([1, 1.35, 1.7])
    periodicidade = c1.selectbox("Periodicidade", PERIODICIDADES, key="sellout_periodicidade")
    opcoes = _opcoes_periodo(df, periodicidade)
    if not opcoes:
        st.warning("Não há períodos disponíveis para esta marca.")
        return
    escolha = c2.selectbox(
        "Período analisado",
        opcoes,
        format_func=lambda valor: _rotulo(periodicidade, valor),
        key=f"sellout_periodo_{periodicidade}",
    )
    if periodicidade == "Anual":
        metodo = "Mesmo período do ano anterior"
        c3.markdown("**Comparação**")
        c3.caption("Ano anterior. No comparativo anual, os dois modelos coincidem.")
    else:
        metodo = c3.radio(
            "Comparação",
            ["Período anterior equivalente", "Mesmo período do ano anterior"],
            horizontal=False,
            key="sellout_metodo_comparacao",
        )

    meses_atual = _meses(periodicidade, escolha)
    meses_base = _comparacao_anterior(periodicidade, escolha, metodo)
    periodo_completo = _filtrar_periodo(df, meses_atual)
    base_completa = _filtrar_periodo(df, meses_base)
    atual, anterior, meses_comparaveis = _meses_comparaveis(df, meses_atual, meses_base)
    qtd_meses_atual = len(set(zip(periodo_completo.year.astype(int), periodo_completo.month.astype(int))))
    qtd_meses_base = len(set(zip(base_completa.year.astype(int), base_completa.month.astype(int))))
    rotulo_atual = _rotulo(periodicidade, escolha)
    rotulo_base = _rotulo_base(periodicidade, meses_base)

    st.markdown("---")
    st.markdown(f"### {rotulo_atual}")
    st.caption(
        f"Cobertura dos arquivos: período atual {qtd_meses_atual}/{len(meses_atual)} mês(es); "
        f"comparação {qtd_meses_base}/{len(meses_base)} mês(es) — {rotulo_base}."
    )

    tem_comparacao = meses_comparaveis > 0
    if tem_comparacao:
        if meses_comparaveis < len(meses_atual):
            st.warning(
                f"Comparação parcial: {meses_comparaveis} mês(es) correspondente(s). "
                "As variações e os indicadores comparativos usam somente esses meses."
            )
        resumo_atual, resumo_base = _resumo(atual), _resumo(anterior)
        produtos = _comparar(
            _agregar(atual, "product_code"),
            _agregar(anterior, "product_code"),
            "product_code",
            resumo_atual["revenue"],
            resumo_base["revenue"],
        )
        lojas = _comparar(
            _agregar(atual, "store"),
            _agregar(anterior, "store"),
            "store",
            resumo_atual["revenue"],
            resumo_base["revenue"],
        )
        st.caption(
            f"Comparação calculada com {meses_comparaveis} mês(es): "
            f"{rotulo_atual} versus {rotulo_base}."
        )
    else:
        resumo_atual = _resumo(periodo_completo)
        resumo_base = _resumo(base_completa)
        produtos = pd.DataFrame()
        lojas = pd.DataFrame()
        st.warning(
            "Ainda não há mês correspondente nos dois períodos. "
            "O resultado será exibido sem variações até importar a base comparativa."
        )

    def _delta(atual_valor, base_valor):
        variacao = _variacao(atual_valor, base_valor)
        return None if variacao is None else f"{variacao:+.2f}%"

    colunas_kpi = st.columns(6)
    colunas_kpi[0].metric(
        "Faturamento", _moeda(resumo_atual["revenue"]),
        _delta(resumo_atual["revenue"], resumo_base["revenue"]) if tem_comparacao else None,
    )
    colunas_kpi[1].metric(
        "Unidades vendidas", f'{resumo_atual["quantity"]:,.0f}'.replace(",", "."),
        _delta(resumo_atual["quantity"], resumo_base["quantity"]) if tem_comparacao else None,
    )
    colunas_kpi[2].metric(
        "Valor médio/unidade", _moeda(resumo_atual["average"]),
        _delta(resumo_atual["average"], resumo_base["average"]) if tem_comparacao else None,
    )
    colunas_kpi[3].metric("Registros", f'{resumo_atual["records"]:,}'.replace(",", "."))
    colunas_kpi[4].metric("SKUs", f'{resumo_atual["skus"]:,}'.replace(",", "."))
    colunas_kpi[5].metric("Lojas", f'{resumo_atual["stores"]:,}'.replace(",", "."))
    st.caption(
        "Valor médio por unidade = faturamento ÷ unidades. Não representa ticket médio por pedido ou cupom."
    )

    tendencia = (
        df.groupby(["year", "month"], as_index=False)
        .agg(faturamento=("revenue", "sum"), unidades=("quantity", "sum"))
        .sort_values(["year", "month"])
    )
    if len(tendencia) > 1:
        tendencia["Período"] = tendencia.apply(
            lambda linha: _rotulo("Mensal", (linha.year, linha.month)), axis=1
        )
        graf1, graf2 = st.columns(2)
        with graf1:
            st.caption("Evolução mensal do faturamento")
            st.line_chart(tendencia.set_index("Período")[["faturamento"]], use_container_width=True)
        with graf2:
            st.caption("Evolução mensal das unidades")
            st.line_chart(tendencia.set_index("Período")[["unidades"]], use_container_width=True)

    if tem_comparacao:
        graf1, graf2 = st.columns(2)
        with graf1:
            st.caption("Faturamento — período comparado")
            st.bar_chart(
                pd.DataFrame(
                    {"Faturamento": [resumo_base["revenue"], resumo_atual["revenue"]]},
                    index=[rotulo_base, rotulo_atual],
                ),
                use_container_width=True,
            )
        with graf2:
            st.caption("Unidades — período comparado")
            st.bar_chart(
                pd.DataFrame(
                    {"Unidades": [resumo_base["quantity"], resumo_atual["quantity"]]},
                    index=[rotulo_base, rotulo_atual],
                ),
                use_container_width=True,
            )

        st.markdown("### Desempenho por produto")
        produtos["Código"] = produtos["product_code"]
        produtos["Referência"] = produtos["reference"]
        produtos["Descrição"] = produtos["description"]
        visao_produtos = produtos.rename(
            columns={
                "revenue_atual": "Faturamento atual",
                "revenue_base": "Faturamento comparação",
                "delta_revenue": "Variação R$",
                "delta_pct": "Variação %",
                "quantity_atual": "Unidades atuais",
                "quantity_base": "Unidades comparação",
                "share_atual": "Share atual %",
                "share_delta": "Variação share (p.p.)",
                "status": "Situação",
            }
        )[
            [
                "Código", "Referência", "Descrição", "Faturamento atual",
                "Faturamento comparação", "Variação R$", "Variação %",
                "Unidades atuais", "Unidades comparação", "Share atual %",
                "Variação share (p.p.)", "Situação",
            ]
        ]
        config_produtos = {
            "Faturamento atual": st.column_config.NumberColumn(format="R$ %.2f"),
            "Faturamento comparação": st.column_config.NumberColumn(format="R$ %.2f"),
            "Variação R$": st.column_config.NumberColumn(format="R$ %.2f"),
            "Variação %": st.column_config.NumberColumn(format="%.2f%%"),
            "Share atual %": st.column_config.NumberColumn(format="%.2f%%"),
            "Variação share (p.p.)": st.column_config.NumberColumn(format="%.2f"),
        }
        aba1, aba2, aba3 = st.tabs(["Maiores avanços", "Maiores retrações", "Todos os SKUs"])
        with aba1:
            avancos = visao_produtos[visao_produtos["Variação R$"] > 0].sort_values(
                "Variação R$", ascending=False
            ).head(30)
            st.dataframe(avancos, use_container_width=True, hide_index=True, column_config=config_produtos)
        with aba2:
            retracoes = visao_produtos[visao_produtos["Variação R$"] < 0].sort_values(
                "Variação R$"
            ).head(30)
            st.dataframe(retracoes, use_container_width=True, hide_index=True, column_config=config_produtos)
        with aba3:
            st.dataframe(
                visao_produtos.sort_values("Faturamento atual", ascending=False),
                use_container_width=True,
                hide_index=True,
                column_config=config_produtos,
            )

        graf1, graf2 = st.columns(2)
        with graf1:
            st.caption("SKUs com maior avanço de faturamento")
            maiores = produtos[produtos.delta_revenue > 0].nlargest(10, "delta_revenue")
            if not maiores.empty:
                st.bar_chart(maiores.set_index("product_code")[["delta_revenue"]], use_container_width=True)
        with graf2:
            st.caption("SKUs com maior retração de faturamento")
            menores = produtos[produtos.delta_revenue < 0].nsmallest(10, "delta_revenue")
            if not menores.empty:
                st.bar_chart(menores.set_index("product_code")[["delta_revenue"]], use_container_width=True)

        st.markdown("### Desempenho por loja")
        visao_lojas = lojas.rename(
            columns={
                "store": "Loja",
                "revenue_atual": "Faturamento atual",
                "revenue_base": "Faturamento comparação",
                "delta_revenue": "Variação R$",
                "delta_pct": "Variação %",
                "quantity_atual": "Unidades atuais",
                "quantity_base": "Unidades comparação",
                "share_atual": "Share atual %",
            }
        )[
            [
                "Loja", "Faturamento atual", "Faturamento comparação",
                "Variação R$", "Variação %", "Unidades atuais",
                "Unidades comparação", "Share atual %",
            ]
        ]
        config_lojas = {
            "Faturamento atual": st.column_config.NumberColumn(format="R$ %.2f"),
            "Faturamento comparação": st.column_config.NumberColumn(format="R$ %.2f"),
            "Variação R$": st.column_config.NumberColumn(format="R$ %.2f"),
            "Variação %": st.column_config.NumberColumn(format="%.2f%%"),
            "Share atual %": st.column_config.NumberColumn(format="%.2f%%"),
        }
        st.dataframe(
            visao_lojas.sort_values("Faturamento atual", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config=config_lojas,
        )
        graf1, graf2 = st.columns(2)
        with graf1:
            st.caption("Lojas com maior avanço")
            maiores_lojas = lojas[lojas.delta_revenue > 0].nlargest(10, "delta_revenue")
            if not maiores_lojas.empty:
                st.bar_chart(maiores_lojas.set_index("store")[["delta_revenue"]], use_container_width=True)
        with graf2:
            st.caption("Lojas com maior retração")
            menores_lojas = lojas[lojas.delta_revenue < 0].nsmallest(10, "delta_revenue")
            if not menores_lojas.empty:
                st.bar_chart(menores_lojas.set_index("store")[["delta_revenue"]], use_container_width=True)

        st.markdown("### Insights gerenciais")
        variacao_receita = _variacao(resumo_atual["revenue"], resumo_base["revenue"])
        variacao_unidades = _variacao(resumo_atual["quantity"], resumo_base["quantity"])
        variacao_media = _variacao(resumo_atual["average"], resumo_base["average"])
        if variacao_receita is not None and variacao_unidades is not None:
            if resumo_atual["revenue"] > resumo_base["revenue"] and resumo_atual["quantity"] <= resumo_base["quantity"]:
                st.markdown("- O faturamento avançou sem crescimento proporcional de unidades; o valor médio por unidade subiu. Os dados não separam reajuste de preço de mudança no mix.")
            elif resumo_atual["revenue"] > resumo_base["revenue"] and resumo_atual["quantity"] > resumo_base["quantity"]:
                st.markdown("- Faturamento e volume cresceram juntos.")
            elif resumo_atual["revenue"] < resumo_base["revenue"] and resumo_atual["quantity"] > resumo_base["quantity"]:
                st.markdown("- O volume cresceu, mas o faturamento recuou. Verifique o mix e o valor realizado por unidade.")
            elif resumo_atual["revenue"] < resumo_base["revenue"] and resumo_atual["quantity"] < resumo_base["quantity"]:
                st.markdown("- Faturamento e volume recuaram juntos. Priorize os SKUs e lojas que mais contribuíram para a queda.")
        if variacao_media is not None:
            st.markdown(f"- O valor médio por unidade variou {variacao_media:+.2f}% frente à comparação.")
        maiores = produtos[produtos.delta_revenue > 0].nlargest(3, "delta_revenue")
        menores = produtos[produtos.delta_revenue < 0].nsmallest(3, "delta_revenue")
        if not maiores.empty:
            st.markdown("- Maiores avanços por código: " + ", ".join(maiores.product_code.astype(str)) + ".")
        if not menores.empty:
            st.markdown("- Maiores retrações por código: " + ", ".join(menores.product_code.astype(str)) + ".")
        st.caption(
            "Sem dados de estoque, pedidos e ações comerciais, o NEXO não atribui causas como ruptura, "
            "promoção ou perda de competitividade."
        )
        st.markdown("### Acompanhamento recomendado")
        if not menores.empty:
            st.markdown("- Investigar a retração dos códigos: " + ", ".join(menores.product_code.astype(str)) + ".")
        if not maiores.empty:
            st.markdown("- Acompanhar a recorrência e a distribuição dos códigos em avanço: " + ", ".join(maiores.product_code.astype(str)) + ".")
        lojas_em_queda = lojas[lojas.delta_revenue < 0].nsmallest(5, "delta_revenue")
        if not lojas_em_queda.empty:
            st.markdown("- Comparar os mesmos SKUs nas lojas em retração: " + ", ".join(lojas_em_queda.store.astype(str)) + ".")

        produtos_exportar, lojas_exportar = produtos, lojas
        periodo_atual_exportar, periodo_base_exportar = atual, anterior
    else:
        st.markdown("### Resultado por produto no período")
        produtos_exportar = _agregar(periodo_completo, "product_code").sort_values("revenue", ascending=False)
        if not produtos_exportar.empty:
            st.bar_chart(
                produtos_exportar.head(10).set_index("product_code")[["revenue"]],
                use_container_width=True,
            )
        st.dataframe(
            produtos_exportar.rename(
                columns={
                    "product_code": "Código", "reference": "Referência",
                    "description": "Descrição", "quantity": "Unidades",
                    "revenue": "Faturamento",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={"Faturamento": st.column_config.NumberColumn(format="R$ %.2f")},
        )
        st.markdown("### Resultado por loja no período")
        lojas_exportar = _agregar(periodo_completo, "store").sort_values("revenue", ascending=False)
        if not lojas_exportar.empty:
            st.bar_chart(
                lojas_exportar.head(10).set_index("store")[["revenue"]],
                use_container_width=True,
            )
        st.dataframe(
            lojas_exportar.rename(
                columns={"store": "Loja", "quantity": "Unidades", "revenue": "Faturamento"}
            ),
            use_container_width=True,
            hide_index=True,
            column_config={"Faturamento": st.column_config.NumberColumn(format="R$ %.2f")},
        )
        periodo_atual_exportar, periodo_base_exportar = periodo_completo, base_completa

    if df["category"].fillna("").astype(str).str.strip().ne("").any():
        st.markdown("### Desempenho por categoria")
        base_categoria = atual if tem_comparacao else periodo_completo
        base_categoria = base_categoria[base_categoria["category"].fillna("").astype(str).str.strip().ne("")]
        if not base_categoria.empty:
            categorias = (
                base_categoria.groupby("category", as_index=False)
                .agg(unidades=("quantity", "sum"), faturamento=("revenue", "sum"))
                .sort_values("faturamento", ascending=False)
            )
            st.dataframe(
                categorias.rename(
                    columns={"category": "Categoria", "unidades": "Unidades", "faturamento": "Faturamento"}
                ),
                use_container_width=True,
                hide_index=True,
                column_config={"Faturamento": st.column_config.NumberColumn(format="R$ %.2f")},
            )
    else:
        st.caption(
            "Categoria não consta nos arquivos importados. O NEXO não classifica produtos automaticamente apenas pela descrição."
        )

    with st.expander("Histórico da base consolidada"):
        historico = (
            df.groupby(["year", "month"], as_index=False)
            .agg(registros=("product_code", "size"), unidades=("quantity", "sum"), faturamento=("revenue", "sum"))
            .sort_values(["year", "month"], ascending=[False, False])
        )
        historico["Período"] = historico.apply(
            lambda linha: _rotulo("Mensal", (linha.year, linha.month)), axis=1
        )
        st.dataframe(
            historico[["Período", "registros", "unidades", "faturamento"]],
            use_container_width=True,
            hide_index=True,
            column_config={"faturamento": st.column_config.NumberColumn(format="R$ %.2f")},
        )

    resumo_exportar = [
        {"Indicador": "Faturamento", "Período atual": resumo_atual["revenue"], "Comparação": resumo_base["revenue"] if tem_comparacao else None},
        {"Indicador": "Unidades", "Período atual": resumo_atual["quantity"], "Comparação": resumo_base["quantity"] if tem_comparacao else None},
        {"Indicador": "Valor médio por unidade", "Período atual": resumo_atual["average"], "Comparação": resumo_base["average"] if tem_comparacao else None},
        {"Indicador": "Registros", "Período atual": resumo_atual["records"], "Comparação": resumo_base["records"] if tem_comparacao else None},
        {"Indicador": "SKUs", "Período atual": resumo_atual["skus"], "Comparação": resumo_base["skus"] if tem_comparacao else None},
        {"Indicador": "Lojas", "Período atual": resumo_atual["stores"], "Comparação": resumo_base["stores"] if tem_comparacao else None},
    ]
    nome_arquivo = (
        f"analise_sellout_{str(marca).lower().replace(' ', '_')}_"
        f"{rotulo_atual.lower().replace(' ', '_').replace('/', '-')}.xlsx"
    )
    st.download_button(
        "Exportar análise para Excel",
        data=_exportar(
            resumo_exportar,
            produtos_exportar,
            lojas_exportar,
            periodo_atual_exportar,
            periodo_base_exportar,
        ),
        file_name=nome_arquivo,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def _mesclar(base_antiga, nova):
    if base_antiga.empty:
        return _normalizar_base(nova)
    chaves_substituidas = {
        (linha.brand, int(linha.year), int(linha.month))
        for linha in nova.itertuples(index=False)
    }
    manter = ~base_antiga.apply(
        lambda linha: (
            linha["brand"], int(linha["year"]), int(linha["month"])
        ) in chaves_substituidas,
        axis=1,
    )
    resultado = pd.concat([base_antiga.loc[manter], nova], ignore_index=True)
    return (
        _normalizar_base(resultado)
        .sort_values(["brand", "year", "month", "store", "product_code"])
        .reset_index(drop=True)
    )

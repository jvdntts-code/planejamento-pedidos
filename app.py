import io
import math
import re
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st

from line_analysis_v2 import render_analise_linha
from tasks_module import render_tasks

st.set_page_config(page_title="NEXO | by JVN", page_icon="◆", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-bottom: 3rem;}
div[data-testid="metric-container"] {border:1px solid rgba(128,128,128,.25); border-radius:12px; padding:12px;}
.small {font-size:.88rem; opacity:.78}
.nexo-brand {
    border: 1px solid rgba(128,128,128,.22);
    border-radius: 16px;
    padding: 16px 16px 14px 16px;
    margin-bottom: 14px;
    background: rgba(37,99,235,.06);
}
.nexo-title {
    font-size: 1.65rem;
    line-height: 1;
    font-weight: 800;
    letter-spacing: .08em;
}
.nexo-by {
    font-size: .72rem;
    opacity: .65;
    margin-left: 4px;
    letter-spacing: .06em;
}
.nexo-subtitle {
    font-size: .78rem;
    opacity: .72;
    margin-top: 8px;
}
.nexo-hero {
    border: 1px solid rgba(128,128,128,.22);
    border-radius: 18px;
    padding: 26px 28px;
    margin-bottom: 20px;
    background: linear-gradient(135deg, rgba(37,99,235,.09), rgba(15,118,110,.05));
}
.nexo-hero h1 {margin: 0; font-size: 2.2rem; letter-spacing: .06em;}
.nexo-hero p {margin: 8px 0 0 0; opacity: .72;}
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown(
    """
    <div class="nexo-brand">
        <div><span class="nexo-title">NEXO</span><span class="nexo-by">by JVN</span></div>
        <div class="nexo-subtitle">Gestão • Planejamento • Inteligência</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown("### Módulos")
pagina = st.sidebar.radio(
    "Escolha a área",
    [
        "🏠 Início",
        "📦 Planejamento de Pedido",
        "📊 Análise de Linha",
        "🔎 Pendências",
        "🧾 Gestão de Pedidos",
        "✅ Minhas Tarefas",
    ],
    label_visibility="collapsed",
)

def render_inicio():
    st.markdown(
        """
        <div class="nexo-hero">
            <h1>NEXO <span style="font-size:.9rem;opacity:.55">by JVN</span></h1>
            <p>Gestão • Planejamento • Inteligência</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Sua central de trabalho")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info("📦 **Planejamento de Pedido**\n\nCalcule necessidades e gere pedidos com memória de cálculo.")
    with c2:
        st.info("📊 **Análise de Linha**\n\nAvalie Curva ABC, cobertura, ruptura, risco, alto e excesso.")
    with c3:
        st.info("✅ **Minhas Tarefas**\n\nOrganize pendências pessoais, prazos e prioridades.")

    st.markdown("### Próximos módulos")
    p1, p2 = st.columns(2)
    with p1:
        st.container(border=True).markdown(
            "🔎 **Pendências**\n\nConfronto de arquivos, divergências, quantidades pendentes e acompanhamento."
        )
    with p2:
        st.container(border=True).markdown(
            "🧾 **Gestão de Pedidos**\n\nAcompanhamento do pedido desde a emissão até o recebimento e finalização."
        )

def render_em_construcao(titulo, descricao):
    st.title(titulo)
    st.info(descricao)
    st.caption("Este módulo já está reservado no NEXO e será construído sem interferir nas ferramentas atuais.")

if pagina == "🏠 Início":
    render_inicio()
    st.stop()

if pagina == "📊 Análise de Linha":
    render_analise_linha()
    st.stop()

if pagina == "🔎 Pendências":
    render_em_construcao(
        "🔎 Pendências",
        "Aqui vamos importar e confrontar as pendências, identificar divergências e acompanhar o que continua em aberto.",
    )
    st.stop()

if pagina == "🧾 Gestão de Pedidos":
    render_em_construcao(
        "🧾 Gestão de Pedidos",
        "Aqui vamos acompanhar cada pedido, fornecedor, status, previsão, recebimentos e saldo pendente.",
    )
    st.stop()

if pagina == "✅ Minhas Tarefas":
    render_tasks()
    st.stop()

st.title("📦 Planejamento Inteligente de Pedido")
st.caption("NEXO | Gestão • Planejamento • Inteligência")

REPORT_BRANCHES = ["M1","M6","M11","M12","M13","M21","M22","M23","M25","M26","M27","M28","M29","M35","M39","M40","M31"]
MANUAL_ORDER_BRANCHES = ["M10","M24","M38","M41","M45"]
ORDER_BRANCHES = ["M1","M6","M10","M11","M12","M13","M21","M22","M23","M24","M25","M26","M27","M28","M29","M35","M38","M39","M40","M41","M45","M31"]
M20_EXTRA_BRANCHES = ["M14","M15","M16","M17","M18","M19"]
VCA_BRANCHES = ["M25","M26","M27","M28","M29"]
SSA_BRANCHES = ["M14","M15","M16","M17","M18","M19"]
PURCHASE_BRANCHES = ORDER_BRANCHES + SSA_BRANCHES
BRANCH_LABEL = {
    "M1":"M01 EUN", "M6":"M06 BPS", "M10":"M10 (MANUAL)", "M11":"M11", "M12":"M12",
    "M13":"M13", "M14":"M14 (MANUAL)", "M15":"M15 (MANUAL)", "M16":"M16 (MANUAL)",
    "M17":"M17 (MANUAL)", "M18":"M18 (MANUAL)", "M19":"M19 (MANUAL)",
    "M21":"M21", "M22":"M22", "M23":"M23", "M24":"M24 (MANUAL)",
    "M25":"M25", "M26":"M26", "M27":"M27", "M28":"M28", "M29":"M29", "M35":"M35",
    "M38":"M38 (MANUAL)", "M39":"M39", "M40":"M40", "M41":"M41 (MANUAL)",
    "M45":"M45 (MANUAL)", "M31":"M31"
}


def norm(s):
    s = str(s).strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '', s)


def read_file(uploaded):
    name = uploaded.name.lower()
    raw = uploaded.getvalue()
    if name.endswith(('.xlsx','.xls')):
        return pd.read_excel(io.BytesIO(raw))
    if name.endswith('.csv'):
        for enc in ('utf-8-sig','utf-8','latin-1'):
            try:
                return pd.read_csv(io.BytesIO(raw), sep=None, engine='python', encoding=enc)
            except Exception:
                pass
    raise ValueError('Arquivo não reconhecido. Use XLSX, XLS ou CSV.')


def find_col(df, *names):
    m = {norm(c): c for c in df.columns}
    for n in names:
        if norm(n) in m:
            return m[norm(n)]
    return None


def num(series, default=0):
    return pd.to_numeric(series, errors='coerce').fillna(default)


def validate_import(df):
    required = ['Codigo','Descicao','NumFabricante','Marca','EmbCompra','Estoque-M20','Minimo-M20','VendasRoni90-M30']
    missing = [c for c in required if find_col(df, c) is None]
    for b in REPORT_BRANCHES:
        for prefix in ['Estoque','Minimo','VendasRoni30','VendasRoni90']:
            expected = f'{prefix}-{b}'
            if find_col(df, expected) is None:
                missing.append(expected)
    return sorted(set(missing))


def standardize(df):
    out = pd.DataFrame()
    out['codigo'] = df[find_col(df,'Codigo')].astype(str).str.replace(r'\.0$','',regex=True).str.strip()
    out['descricao'] = df[find_col(df,'Descicao','Descricao')].fillna('').astype(str)
    out['referencia'] = df[find_col(df,'NumFabricante')].fillna('').astype(str)
    out['marca'] = df[find_col(df,'Marca')].fillna('').astype(str)
    out['emb_compra'] = num(df[find_col(df,'EmbCompra')],1)
    out.loc[out['emb_compra'] <= 0, 'emb_compra'] = 1

    for b in REPORT_BRANCHES + ['M20','M30']:
        for key, prefix in [('estoque','Estoque'),('minimo','Minimo'),('v30','VendasRoni30'),('v90','VendasRoni90')]:
            c = find_col(df, f'{prefix}-{b}')
            out[f'{key}_{b}'] = num(df[c],0) if c else 0
    return out


def qtd_comprar(estoque, minimo_validado, vendas30):
    e = np.asarray(estoque, dtype=float)
    m = np.asarray(minimo_validado, dtype=float)
    v = np.asarray(vendas30, dtype=float)
    return np.where(
        e < m,
        np.where(e <= v, m, (m - e) + v),
        np.where((e - v) < m, v, 0)
    )


def roundup_multiple(qtd, emb):
    qtd = np.maximum(np.asarray(qtd, dtype=float), 0)
    emb = np.maximum(np.asarray(emb, dtype=float), 1)
    return np.ceil(qtd / emb) * emb


def manual_template(base):
    rows = []
    for _, r in base[['codigo','referencia','descricao']].iterrows():
        for filial in MANUAL_ORDER_BRANCHES:
            rows.append({
                'Codigo': r.codigo, 'Referencia': r.referencia, 'Filial': filial,
                'Estoque_Atual': 0, 'Minimo_Atual': 0, 'Vendas_30d': 0, 'Vendas_90d': 0
            })
        for filial in M20_EXTRA_BRANCHES:
            rows.append({
                'Codigo': r.codigo, 'Referencia': r.referencia, 'Filial': filial,
                'Estoque_Atual': '', 'Minimo_Atual': '', 'Vendas_30d': '', 'Vendas_90d': 0
            })
    return pd.DataFrame(rows)


def pend_template(base):
    return pd.DataFrame({
        'CODIGO INTERNO': base['codigo'],
        'REFERENCIA': base['referencia'],
        'QTD PENDENTE': 0
    })


def xlsx_bytes(sheets):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        for name, data in sheets.items():
            data.to_excel(writer, sheet_name=name[:31], index=False)
            ws = writer.book[name[:31]]
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                letter = col[0].column_letter
                max_len = max(len(str(c.value or '')) for c in col[:250])
                ws.column_dimensions[letter].width = min(max(max_len + 2, 11), 38)
    return out.getvalue()


def parse_manual(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=['codigo','filial','estoque','minimo','v30','v90'])
    cols = {
        'codigo': find_col(df,'Codigo','CODIGO INTERNO'),
        'filial': find_col(df,'Filial'),
        'estoque': find_col(df,'Estoque_Atual','Estoque Atual'),
        'minimo': find_col(df,'Minimo_Atual','Minimo Atual'),
        'v30': find_col(df,'Vendas_30d','Vendas 30d'),
        'v90': find_col(df,'Vendas_90d','Vendas 90d'),
    }
    if not cols['codigo'] or not cols['filial']:
        return pd.DataFrame(columns=['codigo','filial','estoque','minimo','v30','v90'])
    x = pd.DataFrame()
    x['codigo'] = df[cols['codigo']].astype(str).str.replace(r'\.0$','',regex=True).str.strip()
    x['filial'] = df[cols['filial']].astype(str).str.upper().str.replace(' ','',regex=False)
    for k in ['estoque','minimo','v30','v90']:
        x[k] = num(df[cols[k]],0) if cols[k] else 0
    return x.groupby(['codigo','filial'], as_index=False).agg({'estoque':'max','minimo':'max','v30':'sum','v90':'sum'})


def parse_pend(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=['codigo','pendencia'])
    ccode = find_col(df,'CODIGO INTERNO','Codigo')
    cqtd = find_col(df,'QTD PENDENTE','Qtd Pendente','Pendencia')
    if not ccode or not cqtd:
        return pd.DataFrame(columns=['codigo','pendencia'])
    x = pd.DataFrame({'codigo':df[ccode].astype(str).str.replace(r'\.0$','',regex=True).str.strip(), 'pendencia':num(df[cqtd],0)})
    return x.groupby('codigo', as_index=False)['pendencia'].sum()


with st.sidebar:
    st.header('Configuração do pedido')

    considerar_necessidade = st.checkbox(
        'Considerar necessidade das filiais',
        value=True,
        help='Quando marcado, soma ao pedido a necessidade calculada das filiais consideradas.'
    )

    st.markdown('**Regiões / filiais**')
    excluir_vca = st.checkbox(
        'Desconsiderar VCA (M25 a M29)',
        value=False,
        help='Retira M25, M26, M27, M28 e M29 somente da necessidade de compra dessas lojas. Elas continuam na análise do mínimo da M20 e no histórico de vendas.'
    )
    excluir_ssa = st.checkbox(
        'Desconsiderar SSA (M14 a M19)',
        value=False,
        help='Retira M14, M15, M16, M17, M18 e M19 somente da necessidade de compra dessas lojas. Elas continuam na análise do mínimo da M20 e no histórico de vendas.'
    )

    leadtime_dias = st.number_input(
        'Lead Time geral (dias)',
        min_value=0,
        max_value=365,
        value=0,
        step=1,
        help='Informe o Lead Time total: fornecedor + processo interno.'
    )

    abater_estoque_m20 = st.checkbox(
        'Abater estoque atual da M20',
        value=True,
        help='Desconta do pedido o estoque disponível na M20.'
    )

    abater_pendencia = st.checkbox(
        'Abater pendência de compra',
        value=True,
        help='Quando marcado, desconta as quantidades importadas no arquivo de pendências.'
    )

    with st.expander('Validação dos mínimos'):
        pct_m20 = st.number_input(
            'Percentual base do mínimo M20',
            min_value=0.0,
            max_value=1.0,
            value=0.25,
            step=0.01,
            format='%.2f'
        )
        st.caption('Mantido para validar e acompanhar o mínimo correto da M20. A planilha original usa 25%.')

    st.markdown('---')
    st.markdown('**Regra do pedido final**')
    partes_regra = []
    if considerar_necessidade:
        partes_regra.append('Necessidade das filiais')
    if leadtime_dias > 0:
        partes_regra.append(f'Lead Time ({leadtime_dias} dias)')
    regra = ' + '.join(partes_regra) if partes_regra else '0'
    if abater_estoque_m20:
        regra += ' − estoque M20'
    if abater_pendencia:
        regra += ' − pendência'
    st.caption(regra + '; depois arredonda pela embalagem de compra.')
    regioes_excluidas = []
    if excluir_vca:
        regioes_excluidas.append('VCA (M25–M29)')
    if excluir_ssa:
        regioes_excluidas.append('SSA (M14–M19)')
    if regioes_excluidas:
        st.caption('Sem pedido direto para: ' + ', '.join(regioes_excluidas) + '.')
    else:
        st.caption('A necessidade de compra de todas as regiões está sendo considerada.')
    st.caption('Importante: essa seleção afeta somente a necessidade de compra das lojas. As regiões continuam integralmente na análise do mínimo da M20 e no cálculo do Lead Time.')

main = st.file_uploader('1) Importe o relatório do sistema', type=['xlsx','xls','csv'], help='Pode ser o mesmo formato usado na aba Importação da planilha.')
if not main:
    st.info('Envie o relatório para começar.')
    st.stop()

try:
    raw = read_file(main)
except Exception as e:
    st.error(str(e)); st.stop()

missing = validate_import(raw)
if missing:
    st.error('O arquivo não tem todas as colunas esperadas pela planilha atual.')
    st.write('Colunas ausentes:', ', '.join(missing[:30]))
    st.stop()

base = standardize(raw)
base = base[base['codigo'].ne('') & base['codigo'].ne('nan')].reset_index(drop=True)

st.success(f'Relatório reconhecido: {len(base)} produtos.')

with st.expander('2) Dados manuais de filiais ausentes no relatório (opcional)'):
    st.caption('M10, M24, M38, M41 e M45 são manuais. M14 a M19 também podem ter necessidade de compra calculada pelos dados manuais e sempre continuam na análise do mínimo da M20.')
    manual_up = st.file_uploader('Importar dados manuais', type=['xlsx','xls','csv'], key='manual')
    st.download_button(
        'Baixar modelo de dados manuais',
        xlsx_bytes({'Dados Manuais': manual_template(base)}),
        file_name='modelo_dados_manuais.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

with st.expander('3) Pendências de compra (opcional)'):
    if abater_pendencia:
        st.caption('Importe as pendências por produto. Elas serão descontadas da necessidade bruta.')
        pend_up = st.file_uploader('Importar pendências', type=['xlsx','xls','csv'], key='pend')
        st.download_button(
            'Baixar modelo de pendências',
            xlsx_bytes({'Pendencias': pend_template(base)}),
            file_name='modelo_pendencias.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        st.info('Abatimento de pendências desativado na configuração do pedido.')
        pend_up = None

manual_df = parse_manual(read_file(manual_up) if manual_up else None)
pend_df = parse_pend(read_file(pend_up) if pend_up else None)
pend_map = pend_df.set_index('codigo')['pendencia'].to_dict() if not pend_df.empty else {}

# lookup manual
manual_lookup = {}
if not manual_df.empty:
    for _, r in manual_df.iterrows():
        manual_lookup[(r.codigo, r.filial)] = r

min_rows = []
need_rows = []
m20_rows = []
final_rows = []

for _, r in base.iterrows():
    codigo = r['codigo']
    necessidade_total = 0.0
    vendas90_filiais_base = 0.0

    for b in PURCHASE_BRANCHES:
        if b in REPORT_BRANCHES:
            estoque = float(r[f'estoque_{b}'])
            minimo = float(r[f'minimo_{b}'])
            v30 = float(r[f'v30_{b}'])
            v90 = float(r[f'v90_{b}'])
        else:
            mr = manual_lookup.get((codigo,b))
            estoque = float(mr.estoque) if mr is not None else 0.0
            minimo = float(mr.minimo) if mr is not None else 0.0
            v30 = float(mr.v30) if mr is not None else 0.0
            v90 = float(mr.v90) if mr is not None else 0.0

        min_valid = max(v90, minimo)
        status_min = 'CORRIGIR' if minimo < v90 else 'OK'
        buy_calculado = float(qtd_comprar([estoque],[min_valid],[v30])[0])

        filial_excluida = (excluir_vca and b in VCA_BRANCHES) or (excluir_ssa and b in SSA_BRANCHES)
        buy_aplicado = 0.0 if filial_excluida else buy_calculado

        necessidade_total += buy_aplicado

        # Para a análise da M20, as regiões continuam sempre consideradas.
        # M14-M19 são somadas separadamente abaixo para preservar a regra original.
        if b not in SSA_BRANCHES:
            vendas90_filiais_base += v90

        regiao = 'VCA' if b in VCA_BRANCHES else ('SSA' if b in SSA_BRANCHES else 'Demais')

        min_rows.append({
            'Codigo':codigo,'Referencia':r.referencia,'Descricao':r.descricao,'Marca':r.marca,
            'Filial':BRANCH_LABEL[b],'Regiao':regiao,
            'Considerada na Necessidade de Compra':'Não' if filial_excluida else 'Sim',
            'Vendas 90d':v90,'Minimo Atual':minimo,'Minimo Validado':min_valid,'Status':status_min
        })
        need_rows.append({
            'Codigo':codigo,'Referencia':r.referencia,'Descricao':r.descricao,'Filial':BRANCH_LABEL[b],
            'Regiao':regiao,
            'Considerada na Necessidade de Compra':'Não' if filial_excluida else 'Sim',
            'Estoque Atual':estoque,'Minimo Validado':min_valid,'Vendas 30d':v30,
            'Qtd Comprar Calculada':buy_calculado,'Qtd Comprar Aplicada':buy_aplicado
        })

    vendas90_extras_calculada = 0.0
    for b in M20_EXTRA_BRANCHES:
        mr = manual_lookup.get((codigo,b))
        vendas90_extras_calculada += float(mr.v90) if mr is not None else 0.0

    # SSA nunca é retirada da análise da M20; a caixa regional afeta somente
    # a necessidade de compra direta das lojas.
    vendas90_extras = vendas90_extras_calculada

    vendas90_m30 = float(r['v90_M30'])
    grupo_25 = vendas90_filiais_base + vendas90_extras + vendas90_m30
    minimo_m20_correto = math.ceil(grupo_25 * pct_m20 + vendas90_m30)
    minimo_m20_atual = float(r['minimo_M20'])
    estoque_m20 = float(r['estoque_M20'])
    pendencia = float(pend_map.get(codigo,0))

    # Lead Time usa a média diária das vendas de 90 dias do mesmo grupo usado
    # para acompanhar o abastecimento da M20.
    media_diaria_grupo = grupo_25 / 90.0
    qtd_leadtime = media_diaria_grupo * float(leadtime_dias)

    necessidade_aplicada = necessidade_total if considerar_necessidade else 0.0
    estoque_abatido = estoque_m20 if abater_estoque_m20 else 0.0
    pendencia_abatida = pendencia if abater_pendencia else 0.0

    necessidade_bruta = max(
        0.0,
        necessidade_aplicada + qtd_leadtime - estoque_abatido - pendencia_abatida
    )
    qtd_final = float(roundup_multiple([necessidade_bruta],[r.emb_compra])[0])

    m20_rows.append({
        'Codigo':codigo,'Referencia':r.referencia,'Descricao':r.descricao,'Marca':r.marca,
        'Vendas 90d Filiais Base M20':vendas90_filiais_base,
        'M14-M19 Vendas 90d M20':vendas90_extras,
        'VCA sem Pedido Direto':'Sim' if excluir_vca else 'Não',
        'SSA sem Pedido Direto':'Sim' if excluir_ssa else 'Não',
        'M30 Vendas 90d':vendas90_m30,'Vendas 90d Grupo p/ Percentual':grupo_25,
        'Percentual Base':pct_m20,'Minimo M20 Atual':minimo_m20_atual,'Minimo M20 Correto':minimo_m20_correto,
        'Status':'OK' if minimo_m20_atual == minimo_m20_correto else 'AJUSTAR',
        'Lead Time Geral (dias)':leadtime_dias,'Media Diaria Grupo 90d':media_diaria_grupo,
        'Cobertura Lead Time':qtd_leadtime,
        'Estoque Atual M20':estoque_m20,'Pendencia Compra':pendencia
    })
    final_rows.append({
        'Codigo':codigo,'Referencia':r.referencia,'Descricao':r.descricao,'Marca':r.marca,
        'Emb. Compra':int(r.emb_compra),
        'Necessidade Geral Filiais Consideradas':necessidade_total,
        'VCA sem Pedido Direto':'Sim' if excluir_vca else 'Não',
        'SSA sem Pedido Direto':'Sim' if excluir_ssa else 'Não',
        'Necessidade Aplicada':necessidade_aplicada,
        'Lead Time Geral (dias)':leadtime_dias,
        'Media Diaria Grupo 90d':media_diaria_grupo,
        'Cobertura Lead Time':qtd_leadtime,
        'Minimo M20 Atual':minimo_m20_atual,
        'Minimo Correto M20':minimo_m20_correto,
        'Estoque Atual M20':estoque_m20,
        'Estoque M20 Abatido':estoque_abatido,
        'Pendencia Compra':pendencia,
        'Pendencia Abatida':pendencia_abatida,
        'Necessidade Bruta':necessidade_bruta,
        'QTD FINAL COMPRA':int(qtd_final)
    })

minimos = pd.DataFrame(min_rows)
necessidades = pd.DataFrame(need_rows)
m20 = pd.DataFrame(m20_rows)
final = pd.DataFrame(final_rows)
pedido = final[final['QTD FINAL COMPRA'] > 0][['Codigo','Referencia','Descricao','Marca','Emb. Compra','QTD FINAL COMPRA']].copy()

configuracao = pd.DataFrame({
    'Parametro': [
        'Considerar necessidade das filiais',
        'Desconsiderar VCA (M25 a M29)',
        'Desconsiderar SSA (M14 a M19)',
        'Lead Time geral (dias)',
        'Abater estoque atual da M20',
        'Abater pendência de compra',
        'Percentual base do mínimo M20'
    ],
    'Valor': [
        'Sim' if considerar_necessidade else 'Não',
        'Sim' if excluir_vca else 'Não',
        'Sim' if excluir_ssa else 'Não',
        leadtime_dias,
        'Sim' if abater_estoque_m20 else 'Não',
        'Sim' if abater_pendencia else 'Não',
        pct_m20
    ]
})

st.markdown('---')
st.subheader('Resultado')

c1,c2,c3,c4 = st.columns(4)
c1.metric('Produtos analisados', len(final))
c2.metric('Produtos no pedido', int((final['QTD FINAL COMPRA']>0).sum()))
c3.metric('Quantidade total', int(final['QTD FINAL COMPRA'].sum()))
c4.metric('Mínimos de filial a corrigir', int((minimos['Status']=='CORRIGIR').sum()))

search = st.text_input('Buscar código, referência ou descrição')
show_final = final.copy()
if search.strip():
    s = search.lower().strip()
    mask = (show_final['Codigo'].astype(str).str.lower().str.contains(s,na=False) |
            show_final['Referencia'].astype(str).str.lower().str.contains(s,na=False) |
            show_final['Descricao'].astype(str).str.lower().str.contains(s,na=False))
    show_final = show_final[mask]

st.subheader('Pedido final por produto')
st.dataframe(show_final, use_container_width=True, hide_index=True)

with st.expander('Ver necessidade por filial'):
    st.dataframe(necessidades, use_container_width=True, hide_index=True)

with st.expander('Ver validação dos mínimos das filiais'):
    st.dataframe(minimos, use_container_width=True, hide_index=True)

with st.expander('Ver cálculo do mínimo da M20'):
    st.dataframe(m20, use_container_width=True, hide_index=True)

export = xlsx_bytes({
    'Pedido Final': pedido,
    'Calculo Final': final,
    'Necessidade Filiais': necessidades,
    'Minimos Filiais': minimos,
    'Minimo M20': m20,
    'Dados Importados': raw,
    'Dados Manuais': manual_df,
    'Pendencias': pend_df,
    'Configuracao': configuracao,
})

st.download_button(
    '⬇️ Exportar pedido e memória de cálculo (.xlsx)',
    export,
    file_name='pedido_final_calculado.xlsx',
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    type='primary'
)

st.caption('Os mínimos das filiais continuam validados pelo maior valor entre mínimo cadastrado e vendas de 90 dias. As caixas de VCA (M25–M29) e SSA (M14–M19) retiram somente a necessidade de compra direta dessas lojas. Todas elas continuam compondo normalmente a análise do mínimo da M20 e o histórico usado no Lead Time. O pedido final é arredondado pela embalagem de compra.')

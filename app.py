import io
import math
import re
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Planejamento de Pedido", page_icon="📦", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-bottom: 3rem;}
div[data-testid="metric-container"] {border:1px solid rgba(128,128,128,.25); border-radius:12px; padding:12px;}
.small {font-size:.88rem; opacity:.78}
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("## Módulos")
pagina = st.sidebar.radio(
    "Escolha a área",
    ["📦 Planejamento de Pedido", "📊 Análise de Linha"],
    label_visibility="collapsed"
)

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



def standardize_line_report(df):
    required_map = {
        'codigo': ('Codigo',),
        'descricao': ('Descrição','Descricao'),
        'referencia': ('NumFabricante','Numero Fabricante'),
        'linha_codigo': ('CodLinha','Codigo Linha'),
        'linha_nome': ('Nome','Nome Linha','Linha'),
        'estoque': ('Estoque do Grupo','Estoque Grupo'),
        'minimo': ('estoqueMinGrupo','Estoque Min Grupo','Minimo Grupo'),
        'vendas30': ('Vendas30diasRoni','Vendas 30 dias'),
        'vendas60': ('Vendas60diasRoni','Vendas 60 dias'),
        'vendas90': ('Vendas90diasRoni','Vendas 90 dias'),
        'preco_venda': ('Preço Venda','Preco Venda'),
    }

    resolved = {}
    missing = []
    for key, aliases in required_map.items():
        col = find_col(df, *aliases)
        if not col:
            missing.append(aliases[0])
        else:
            resolved[key] = col

    long_col = find_col(df, 'Vendas360diasRoni','Vendas365diasRoni','Vendas 360 dias','Vendas 365 dias')
    if not long_col:
        missing.append('Vendas360diasRoni')

    if missing:
        raise ValueError('Colunas ausentes no relatório: ' + ', '.join(missing))

    long_days = 365 if '365' in norm(long_col) else 360
    out = pd.DataFrame()
    out['codigo'] = df[resolved['codigo']].astype(str).str.replace(r'\.0
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
,'',regex=True).str.strip()
    out['descricao'] = df[resolved['descricao']].fillna('').astype(str).str.strip()
    out['referencia'] = df[resolved['referencia']].fillna('').astype(str).str.strip()
    out['linha_codigo'] = df[resolved['linha_codigo']].astype(str).str.replace(r'\.0
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
,'',regex=True).str.strip()
    out['linha_nome'] = df[resolved['linha_nome']].fillna('SEM LINHA').astype(str).str.strip()

    for key in ['estoque','minimo','vendas30','vendas60','vendas90','preco_venda']:
        out[key] = num(df[resolved[key]], 0)

    out['vendas_longo'] = num(df[long_col], 0)
    out['linha'] = np.where(
        out['linha_nome'].str.strip().ne(''),
        out['linha_codigo'].str.strip() + ' - ' + out['linha_nome'].str.strip(),
        out['linha_codigo'].str.strip()
    )
    out['valor_estoque'] = out['estoque'] * out['preco_venda']
    out['faturamento_90'] = out['vendas90'] * out['preco_venda']
    out['faturamento_longo'] = out['vendas_longo'] * out['preco_venda']
    out = out[out['codigo'].ne('') & out['codigo'].ne('nan')].reset_index(drop=True)
    return out, long_days


def abc_with_ties(revenue):
    revenue = pd.to_numeric(revenue, errors='coerce').fillna(0)
    total = float(revenue.sum())
    if total <= 0:
        return pd.Series(['C'] * len(revenue), index=revenue.index), pd.Series([1.0] * len(revenue), index=revenue.index)

    grouped = revenue.groupby(revenue).sum().sort_index(ascending=False)
    cumulative = (grouped.cumsum() / total).to_dict()
    share_acc = revenue.map(cumulative).fillna(1.0)
    curve = np.select(
        [share_acc <= 0.80, share_acc <= 0.95],
        ['A','B'],
        default='C'
    )
    return pd.Series(curve, index=revenue.index), share_acc


def classify_coverage(stock, sales, days, curve):
    if sales <= 0:
        if stock > 0:
            return 'SEM VENDA - ESTOQUE PARADO'
        if stock < 0:
            return 'ESTOQUE NEGATIVO'
        return 'SEM VENDA / SEM ESTOQUE'

    coverage = stock / (sales / days)
    if curve == 'A':
        if coverage < 30:
            return 'PERIGOSO'
        if coverage < 90:
            return 'ABAIXO DO RECOMENDADO'
        if coverage <= 180:
            return 'OK'
        return 'EXCESSO'

    if curve == 'B':
        if coverage < 30:
            return 'PERIGOSO'
        if coverage < 90:
            return 'ABAIXO DO RECOMENDADO'
        if coverage <= 120:
            return 'OK'
        if coverage <= 150:
            return 'ALTO'
        return 'EXCESSO'

    if coverage < 30:
        return 'PERIGOSO'
    if coverage < 90:
        return 'ABAIXO DO RECOMENDADO'
    if coverage <= 120:
        return 'OK'
    return 'EXCESSO'


def giro_curva_c(stock, sales, days, curve):
    if curve != 'C':
        return ''
    if sales <= 0:
        if stock > 0:
            return 'SEM VENDA - ESTOQUE PARADO'
        if stock < 0:
            return 'ESTOQUE NEGATIVO'
        return 'SEM VENDA / SEM ESTOQUE'
    coverage = stock / (sales / days)
    if coverage <= 30:
        return 'BOA'
    if coverage <= 90:
        return 'ATENÇÃO'
    if coverage <= 100:
        return 'ALTO'
    return 'EXCESSO'


def build_line_analysis(base, period_days, long_days):
    x = base.copy()
    if period_days == 90:
        x['vendas_periodo'] = x['vendas90']
        x['faturamento_periodo'] = x['faturamento_90']
    else:
        x['vendas_periodo'] = x['vendas_longo']
        x['faturamento_periodo'] = x['faturamento_longo']

    x['curva_abc'], x['participacao_acumulada'] = abc_with_ties(x['faturamento_periodo'])
    total_fat = float(x['faturamento_periodo'].sum())
    x['participacao_faturamento'] = np.where(
        total_fat != 0,
        x['faturamento_periodo'] / total_fat,
        0
    )
    x['media_diaria'] = x['vendas_periodo'] / float(period_days)
    x['cobertura_dias'] = np.where(
        x['media_diaria'] > 0,
        x['estoque'] / x['media_diaria'],
        np.nan
    )
    x['status'] = [
        classify_coverage(float(e), float(v), period_days, curva)
        for e, v, curva in zip(x['estoque'], x['vendas_periodo'], x['curva_abc'])
    ]
    x['alerta_giro_c'] = [
        giro_curva_c(float(e), float(v), period_days, curva)
        for e, v, curva in zip(x['estoque'], x['vendas_periodo'], x['curva_abc'])
    ]

    keys = ['linha_codigo','linha_nome','linha']
    summary = x.groupby(keys, as_index=False).agg(
        itens=('codigo','count'),
        faturamento_90=('faturamento_90','sum'),
        faturamento_longo=('faturamento_longo','sum'),
        estoque_lojas=('estoque','sum'),
        valor_estoque=('valor_estoque','sum'),
    )

    high = x['status'].isin(['ALTO','EXCESSO'])
    stopped = x['status'].eq('SEM VENDA - ESTOQUE PARADO')

    def grouped_metric(mask, source, name, how='sum'):
        tmp = x.loc[mask].groupby(keys)[source]
        s = tmp.count() if how == 'count' else tmp.sum()
        return s.rename(name).reset_index()

    summary = summary.merge(grouped_metric(high, 'codigo', 'itens_alto_excesso', 'count'), on=keys, how='left')
    summary = summary.merge(grouped_metric(high, 'estoque', 'unid_alto_excesso'), on=keys, how='left')
    summary = summary.merge(grouped_metric(high, 'valor_estoque', 'valor_alto_excesso'), on=keys, how='left')
    summary = summary.merge(grouped_metric(stopped, 'codigo', 'itens_parados', 'count'), on=keys, how='left')
    summary = summary.merge(grouped_metric(stopped, 'estoque', 'unid_paradas'), on=keys, how='left')
    summary = summary.merge(grouped_metric(stopped, 'valor_estoque', 'valor_parado'), on=keys, how='left')

    for status in ['PERIGOSO','ABAIXO DO RECOMENDADO','OK','ALTO','EXCESSO','SEM VENDA / SEM ESTOQUE','ESTOQUE NEGATIVO']:
        slug = norm(status)
        counts = (
            x[x['status'].eq(status)]
            .groupby(keys)['codigo']
            .count()
            .rename(slug)
            .reset_index()
        )
        summary = summary.merge(counts, on=keys, how='left')

    numeric_fill = [
        'itens_alto_excesso','unid_alto_excesso','valor_alto_excesso',
        'itens_parados','unid_paradas','valor_parado',
        'perigoso','abaixodorecomendado','ok','alto','excesso',
        'semvendasemestoque','estoquenegativo'
    ]
    for col in numeric_fill:
        if col not in summary.columns:
            summary[col] = 0
        summary[col] = summary[col].fillna(0)

    total_items = max(float(summary['itens'].sum()), 1)
    total_stock = float(summary['estoque_lojas'].sum())
    total_stock_value = float(summary['valor_estoque'].sum())
    total_fat90 = float(summary['faturamento_90'].sum())
    total_fatlong = float(summary['faturamento_longo'].sum())
    total_excess_value = float(summary['valor_alto_excesso'].sum())

    summary['pct_itens'] = summary['itens'] / total_items
    summary['pct_fat_90'] = np.where(total_fat90 != 0, summary['faturamento_90'] / total_fat90, 0)
    summary['pct_fat_longo'] = np.where(total_fatlong != 0, summary['faturamento_longo'] / total_fatlong, 0)
    summary['pct_estoque'] = np.where(total_stock != 0, summary['estoque_lojas'] / total_stock, 0)
    summary['pct_valor_estoque'] = np.where(total_stock_value != 0, summary['valor_estoque'] / total_stock_value, 0)
    summary['pct_valor_excesso'] = np.where(total_excess_value != 0, summary['valor_alto_excesso'] / total_excess_value, 0)

    sort_col = 'faturamento_90' if period_days == 90 else 'faturamento_longo'
    summary = summary.sort_values(sort_col, ascending=False).reset_index(drop=True)
    return x, summary


def render_analise_linha():
    st.title('📊 Análise de Linha')
    st.caption('Curva ABC, cobertura, excesso, estoque parado e representatividade por linha — direto do relatório bruto do sistema.')

    upload = st.file_uploader(
        'Importe o relatório bruto por marca',
        type=['xlsx','xls','csv'],
        key='linha_raw',
        help='Use o arquivo exatamente como ele sai do sistema.'
    )
    if not upload:
        st.info('Envie o relatório bruto para gerar a análise de linha.')
        return

    try:
        raw_line = read_file(upload)
        base_line, long_days = standardize_line_report(raw_line)
    except Exception as e:
        st.error(str(e))
        return

    periodo_opcoes = ['90 dias', f'{long_days} dias']
    periodo = st.radio(
        'Período principal da análise',
        periodo_opcoes,
        horizontal=True,
        key='periodo_linha'
    )
    period_days = 90 if periodo == '90 dias' else long_days
    produtos, resumo = build_line_analysis(base_line, period_days, long_days)

    faturamento_col = 'faturamento_90' if period_days == 90 else 'faturamento_longo'
    total_faturamento = float(produtos['faturamento_periodo'].sum())
    total_estoque = float(produtos['estoque'].sum())
    valor_estoque = float(produtos['valor_estoque'].sum())
    mask_excesso = produtos['status'].isin(['ALTO','EXCESSO'])
    mask_parado = produtos['status'].eq('SEM VENDA - ESTOQUE PARADO')

    valor_excesso = float(produtos.loc[mask_excesso, 'valor_estoque'].sum())
    valor_parado = float(produtos.loc[mask_parado, 'valor_estoque'].sum())

    st.success(f'Relatório reconhecido: {len(produtos)} produtos em {produtos["linha"].nunique()} linhas.')

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('SKUs analisados', f'{len(produtos):,}'.replace(',','.'))
    c2.metric(f'Faturamento {period_days}d', f'R$ {total_faturamento:,.2f}'.replace(',', 'X').replace('.', ',').replace('X','.'))
    c3.metric('Estoque lojas', f'{total_estoque:,.0f}'.replace(',','.'))
    c4.metric('Valor do estoque', f'R$ {valor_estoque:,.2f}'.replace(',', 'X').replace('.', ',').replace('X','.'))

    c5, c6, c7 = st.columns(3)
    c5.metric('Itens alto/excesso', int(mask_excesso.sum()))
    c6.metric('Valor alto/excesso', f'R$ {valor_excesso:,.2f}'.replace(',', 'X').replace('.', ',').replace('X','.'))
    c7.metric('Valor parado', f'R$ {valor_parado:,.2f}'.replace(',', 'X').replace('.', ',').replace('X','.'))

    if not resumo.empty:
        maior_venda = resumo.loc[resumo[faturamento_col].idxmax()]
        maior_excesso = resumo.loc[resumo['valor_alto_excesso'].idxmax()]
        maior_estoque = resumo.loc[resumo['estoque_lojas'].idxmax()]
        mais_itens = resumo.loc[resumo['itens'].idxmax()]

        st.markdown('### Destaques')
        d1, d2, d3, d4 = st.columns(4)
        d1.metric('Linha que mais vende', maior_venda['linha'], f'{(maior_venda[faturamento_col] / total_faturamento * 100) if total_faturamento else 0:.1f}% do faturamento')
        d2.metric('Maior excesso', maior_excesso['linha'], f'R$ {maior_excesso["valor_alto_excesso"]:,.0f}'.replace(',', '.'))
        d3.metric('Maior estoque', maior_estoque['linha'], f'{maior_estoque["estoque_lojas"]:,.0f} un.'.replace(',', '.'))
        d4.metric('Mais SKUs', mais_itens['linha'], f'{int(mais_itens["itens"])} itens')

    linhas = resumo['linha'].tolist()
    linha_escolhida = st.selectbox('Detalhar linha', ['Todas as linhas'] + linhas, key='linha_detalhe')

    produtos_filtro = produtos.copy()
    resumo_filtro = resumo.copy()
    if linha_escolhida != 'Todas as linhas':
        produtos_filtro = produtos_filtro[produtos_filtro['linha'].eq(linha_escolhida)].copy()
        resumo_filtro = resumo_filtro[resumo_filtro['linha'].eq(linha_escolhida)].copy()

    tab1, tab2, tab3 = st.tabs(['Visão por linha', 'Excesso e parados', 'Produtos'])

    with tab1:
        st.markdown('#### Representatividade por linha')
        display = resumo_filtro[[
            'linha','itens','pct_itens','faturamento_90','pct_fat_90',
            'faturamento_longo','pct_fat_longo','estoque_lojas','pct_estoque',
            'valor_estoque','pct_valor_estoque','itens_alto_excesso',
            'unid_alto_excesso','valor_alto_excesso','pct_valor_excesso',
            'itens_parados','unid_paradas','valor_parado',
            'perigoso','abaixodorecomendado','ok','alto','excesso',
            'semvendasemestoque','estoquenegativo'
        ]].copy()

        display.columns = [
            'Linha','Itens','% Itens','Faturamento 90d','% Fat. 90d',
            f'Faturamento {long_days}d',f'% Fat. {long_days}d','Estoque Lojas','% Estoque',
            'Valor Estoque','% Valor Estoque','Itens Alto/Excesso',
            'Unid. Alto/Excesso','Valor Alto/Excesso','% Valor Excesso',
            'Itens Parados','Unid. Paradas','Valor Parado',
            'Perigoso','Abaixo Recomend.','OK','Alto','Excesso',
            'Sem Venda/Sem Estoque','Estoque Negativo'
        ]

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                '% Itens': st.column_config.NumberColumn(format='%.1f%%'),
                '% Fat. 90d': st.column_config.NumberColumn(format='%.1f%%'),
                f'% Fat. {long_days}d': st.column_config.NumberColumn(format='%.1f%%'),
                '% Estoque': st.column_config.NumberColumn(format='%.1f%%'),
                '% Valor Estoque': st.column_config.NumberColumn(format='%.1f%%'),
                '% Valor Excesso': st.column_config.NumberColumn(format='%.1f%%'),
                'Faturamento 90d': st.column_config.NumberColumn(format='R$ %.2f'),
                f'Faturamento {long_days}d': st.column_config.NumberColumn(format='R$ %.2f'),
                'Valor Estoque': st.column_config.NumberColumn(format='R$ %.2f'),
                'Valor Alto/Excesso': st.column_config.NumberColumn(format='R$ %.2f'),
                'Valor Parado': st.column_config.NumberColumn(format='R$ %.2f'),
            }
        )

        if linha_escolhida == 'Todas as linhas' and len(resumo) > 1:
            chart_df = resumo.set_index('linha')[[faturamento_col]].rename(
                columns={faturamento_col: f'Faturamento {period_days}d'}
            )
            st.markdown('#### Faturamento por linha')
            st.bar_chart(chart_df, use_container_width=True)

    with tab2:
        tipo = st.radio(
            'Mostrar',
            ['Alto / Excesso', 'Estoque parado'],
            horizontal=True,
            key='tipo_alerta_linha'
        )
        if tipo == 'Alto / Excesso':
            alerta = produtos_filtro[produtos_filtro['status'].isin(['ALTO','EXCESSO'])].copy()
        else:
            alerta = produtos_filtro[produtos_filtro['status'].eq('SEM VENDA - ESTOQUE PARADO')].copy()

        alerta_show = alerta[[
            'codigo','referencia','descricao','linha','estoque','minimo',
            'vendas90','vendas_longo','preco_venda','curva_abc',
            'cobertura_dias','status','valor_estoque'
        ]].copy()
        alerta_show.columns = [
            'Código','Referência','Descrição','Linha','Estoque','Mínimo',
            'Vendas 90d',f'Vendas {long_days}d','Preço Venda','Curva ABC',
            'Cobertura (dias)','Status','Valor Estoque'
        ]
        st.dataframe(
            alerta_show,
            use_container_width=True,
            hide_index=True,
            column_config={
                'Preço Venda': st.column_config.NumberColumn(format='R$ %.2f'),
                'Valor Estoque': st.column_config.NumberColumn(format='R$ %.2f'),
                'Cobertura (dias)': st.column_config.NumberColumn(format='%.1f'),
            }
        )

    with tab3:
        f1, f2 = st.columns(2)
        curvas = f1.multiselect('Curva ABC', ['A','B','C'], default=['A','B','C'], key='filtro_curva_linha')
        status_opts = sorted(produtos_filtro['status'].dropna().unique().tolist())
        status_sel = f2.multiselect('Status', status_opts, default=status_opts, key='filtro_status_linha')

        detail = produtos_filtro[
            produtos_filtro['curva_abc'].isin(curvas) &
            produtos_filtro['status'].isin(status_sel)
        ].copy()
        detail_show = detail[[
            'codigo','referencia','descricao','linha','estoque','minimo',
            'vendas30','vendas60','vendas90','vendas_longo','preco_venda',
            'faturamento_periodo','curva_abc','participacao_acumulada',
            'cobertura_dias','status','alerta_giro_c','valor_estoque'
        ]].copy()
        detail_show.columns = [
            'Código','Referência','Descrição','Linha','Estoque','Mínimo',
            'Vendas 30d','Vendas 60d','Vendas 90d',f'Vendas {long_days}d','Preço Venda',
            f'Faturamento {period_days}d','Curva ABC','Participação Acumulada',
            'Cobertura (dias)','Status','Giro Curva C','Valor Estoque'
        ]
        st.dataframe(
            detail_show,
            use_container_width=True,
            hide_index=True,
            column_config={
                'Preço Venda': st.column_config.NumberColumn(format='R$ %.2f'),
                f'Faturamento {period_days}d': st.column_config.NumberColumn(format='R$ %.2f'),
                'Valor Estoque': st.column_config.NumberColumn(format='R$ %.2f'),
                'Participação Acumulada': st.column_config.NumberColumn(format='%.1f%%'),
                'Cobertura (dias)': st.column_config.NumberColumn(format='%.1f'),
            }
        )

    export_summary = resumo.copy()
    export_products = produtos.copy()
    export_excess = produtos[produtos['status'].isin(['ALTO','EXCESSO'])].copy()
    export_stopped = produtos[produtos['status'].eq('SEM VENDA - ESTOQUE PARADO')].copy()

    export = xlsx_bytes({
        'Resumo por Linha': export_summary,
        'Produtos Analisados': export_products,
        'Alto e Excesso': export_excess,
        'Estoque Parado': export_stopped,
        'Relatorio Bruto': raw_line,
    })
    st.download_button(
        '⬇️ Exportar análise de linha (.xlsx)',
        data=export,
        file_name=f'analise_linha_{period_days}d.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        type='primary',
        key='download_analise_linha'
    )

    with st.expander('Critérios utilizados'):
        st.markdown(
            '**Curva ABC:** A até 80% do faturamento acumulado; B de 80% a 95%; C acima de 95%.\n\n'
            '**Curva A:** <30 dias Perigoso; 30–<90 Abaixo; 90–180 OK; >180 Excesso.\n\n'
            '**Curva B:** <30 Perigoso; 30–<90 Abaixo; 90–120 OK; >120–150 Alto; >150 Excesso.\n\n'
            '**Curva C:** <30 Perigoso; 30–<90 Abaixo; 90–120 OK; >120 Excesso.\n\n'
            'Itens sem venda e com saldo positivo são classificados como **Estoque parado**.'
        )


if pagina == "📊 Análise de Linha":
    render_analise_linha()
    st.stop()

st.title("📦 Planejamento Inteligente de Pedido")
st.caption("Versão baseada na lógica da planilha PLANEJAMENTO_PEDIDO_COM_IMPORTACAO_AUTOMATICA.")


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

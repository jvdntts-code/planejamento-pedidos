# Planejamento Inteligente de Pedido

Este projeto reproduz em formato de site a lógica da planilha `PLANEJAMENTO_PEDIDO_COM_IMPORTACAO_AUTOMATICA`.

## O que ele faz

- recebe o mesmo relatório de importação usado pela planilha;
- valida o mínimo de cada filial: o mínimo não pode ser menor que as vendas de 90 dias;
- calcula a quantidade de compra de cada filial usando estoque atual, mínimo validado e vendas de 30 dias;
- mantém campos opcionais para as filiais manuais M10, M24, M38, M41 e M45;
- aceita vendas de 90 dias de M14 a M19 para o cálculo da M20;
- calcula o mínimo correto da M20 com percentual configurável (25% por padrão) e vendas de 90 dias da M30;
- desconta o estoque da M20 e as pendências de compra;
- arredonda a compra final para o múltiplo da embalagem de compra;
- exporta o pedido final e toda a memória de cálculo para Excel.

## Rodar no computador

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Publicar como site

Forma recomendada:

1. crie uma conta no GitHub;
2. crie um repositório e envie estes arquivos;
3. conecte esse repositório ao Streamlit Community Cloud;
4. escolha `app.py` como arquivo principal;
5. o Streamlit fornecerá uma URL `*.streamlit.app`.

## Arquivos

- `app.py` — aplicativo;
- `requirements.txt` — dependências;
- `README.md` — instruções.

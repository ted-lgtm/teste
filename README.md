# App de Controle de Planos MDR

Aplicativo em Streamlit que lê tabelas de MDR a partir de imagens, normaliza os dados, compara com uma base Excel existente e permite salvar novos planos.

## Requisitos

- Python 3.10+
- Tesseract OCR instalado e disponível no sistema (`tesseract` no PATH)

## Instalação

Instale o binário do Tesseract OCR antes de rodar o app. Em distribuições Debian/Ubuntu:

```bash
sudo apt-get update && sudo apt-get install -y tesseract-ocr
```

No Windows/Mac, instale o pacote equivalente e aponte o caminho do executável em `TESSERACT_CMD` ou na barra lateral do app.

```bash
pip install -r requirements.txt
```

## Executar

```bash
streamlit run app.py
```

Para ambientes sem interface gráfica, rode em modo headless escolhendo a porta desejada:

```bash
streamlit run app.py --server.headless true --server.port 8501
```

Use a barra lateral para informar o caminho do arquivo Excel da base. Se o arquivo não existir, será criado automaticamente com a aba `BASE_PLANOS`.

Para o OCR funcionar, confirme que o Tesseract foi encontrado. O app exibe o status na barra lateral e permite ajustar o caminho manual do executável (`TESSERACT_CMD`).

## Funções principais

- `ler_imagem_e_extrair_tabela` – aplica OCR e tenta reconstruir a tabela de MDR.
- `normalizar_tabela` – normaliza modalidades, bandeiras e converte porcentagens para números.
- `gerar_hash_plano` – gera assinatura determinística para o plano.
- `carregar_base_excel` – carrega (ou cria) a aba `BASE_PLANOS` no Excel.
- `comparar_com_base` – identifica planos existentes com o mesmo hash.
- `salvar_plano_na_base` – adiciona um novo plano à base.

## Configuração do Excel

Por padrão o app usa `Buscador de Planos Novo.xlsm`. Ajuste pelo campo na barra lateral ou defina a variável de ambiente `MDR_EXCEL_PATH`.

## Casos de teste sugeridos

1. **Plano idêntico existente**: use uma imagem de tabela com valores iguais a um plano já presente no Excel para validar a detecção de plano existente.
2. **Plano novo**: tabela com MDRs ou prazos diferentes para confirmar que o app pede um novo nome e salva na aba `BASE_PLANOS`.
3. **Taxa de antecipação ausente**: imagem sem linha de antecipação para verificar que o campo fica vazio e o hash muda apenas pelas linhas principais.
4. **Modalidades e bandeiras em letras variadas**: tabelas com variações como "Crédito À vista", "credito a VISTA" para testar a normalização.
5. **Parcelamentos específicos**: imagens com faixas 2-6x, 7-12x e 13-21x para verificar `parcela_de` e `parcela_ate`.
6. **Erros de OCR**: imagens propositalmente borradas para checar a necessidade de edição manual via `st.data_editor` antes de normalizar.

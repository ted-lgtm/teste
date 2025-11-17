import hashlib
import io
import os
import shutil
from datetime import datetime
from typing import List, Tuple

import pandas as pd
import pytesseract
import streamlit as st
from PIL import Image, ImageFilter, ImageOps
from openpyxl import Workbook

# Configurações iniciais
DEFAULT_EXCEL_PATH = os.environ.get("MDR_EXCEL_PATH", "Buscador de Planos Novo.xlsm")
BANDEIRAS_PADRAO = ["VISA", "MASTERCARD", "ELO", "AMEX", "HIPERCARD"]
DEFAULT_TESSERACT_CMD = os.environ.get("TESSERACT_CMD", pytesseract.pytesseract.tesseract_cmd)


# --------------------------
# Funções de utilidade
# --------------------------
def ler_imagem_e_extrair_tabela(file: io.BytesIO) -> Tuple[pd.DataFrame, float]:
    """Lê a imagem enviada, aplica OCR e tenta reconstruir a tabela.

    Retorna um DataFrame com colunas: modalidade, BANDEIRAS_PADRAO..., prazo_recebimento
    e a taxa de antecipação identificada (ou None).
    """
    image = Image.open(file).convert("RGB")
    # Pré-processamento simples para melhorar o OCR
    grayscale = ImageOps.grayscale(image)
    enhanced = grayscale.filter(ImageFilter.MedianFilter())
    # Binarização leve
    threshold = enhanced.point(lambda x: 0 if x < 160 else 255, "1")

    try:
        text = pytesseract.image_to_string(threshold, lang="por")
    except pytesseract.pytesseract.TesseractNotFoundError as exc:  # noqa: PERF203
        raise RuntimeError(
            "Tesseract OCR não encontrado. Configure o caminho correto na barra lateral ou instale o pacote tesseract-ocr."
        ) from exc
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    taxa_antecipacao = None
    linhas_tabela: List[str] = []
    for line in lines:
        if "antecip" in line.lower():
            # Procura a primeira porcentagem na linha
            taxa_match = _extrair_percentuais(line)
            if taxa_match:
                taxa_antecipacao = taxa_match[0]
        else:
            linhas_tabela.append(line)

    header_detectada = _detectar_header(linhas_tabela)
    bandeiras = header_detectada if header_detectada else BANDEIRAS_PADRAO

    registros = []
    for line in linhas_tabela:
        if not _parece_modalidade(line):
            continue
        modalidade_texto = line
        percentuais = _extrair_percentuais(line)
        prazo = _extrair_prazo(line)
        # Garante tamanho de lista igual ao número de bandeiras
        percentuais += [None] * (len(bandeiras) - len(percentuais))
        linha = {"modalidade": modalidade_texto, "prazo_recebimento": prazo}
        for bandeira, taxa in zip(bandeiras, percentuais):
            linha[bandeira] = taxa
        registros.append(linha)

    if not registros:
        return pd.DataFrame(columns=["modalidade", *bandeiras, "prazo_recebimento"]), taxa_antecipacao

    df = pd.DataFrame(registros)
    # Reordena colunas
    ordered_cols = ["modalidade", *bandeiras, "prazo_recebimento"]
    df = df[[col for col in ordered_cols if col in df.columns]]
    return df, taxa_antecipacao


def _extrair_percentuais(texto: str) -> List[float]:
    import re

    encontrados = re.findall(r"(\d+[\.,]?\d*)\s*%?", texto)
    percentuais = []
    for valor in encontrados:
        valor = valor.replace(",", ".")
        try:
            percentuais.append(float(valor))
        except ValueError:
            continue
    return percentuais


def _extrair_prazo(texto: str) -> str:
    import re

    match = re.search(r"D\s*\+\s*\d+", texto, flags=re.IGNORECASE)
    return match.group(0).replace(" ", "").upper() if match else ""


def _parece_modalidade(texto: str) -> bool:
    texto_lower = texto.lower()
    keywords = [
        "debito",
        "débito",
        "credito",
        "crédito",
        "avista",
        "a vista",
        "x",
    ]
    return any(k in texto_lower for k in keywords)


def _detectar_header(linhas: List[str]) -> List[str]:
    # Procura linha que contenha bandeiras conhecidas
    for line in linhas:
        encontrados = []
        lower_line = line.lower()
        for b in BANDEIRAS_PADRAO:
            if b.lower() in lower_line:
                encontrados.append(b)
        if len(encontrados) >= 3:
            return encontrados
    return []


def _tesseract_disponivel(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def normalizar_tabela(df: pd.DataFrame, taxa_antecipacao: float = None) -> pd.DataFrame:
    """Normaliza o DataFrame extraído para o formato esperado da base."""
    registros = []
    for _, row in df.iterrows():
        canal = _normalizar_modalidade(row.get("modalidade", ""))
        if not canal:
            continue
        parcela_de, parcela_ate = _faixa_parcelas(canal)
        prazo = str(row.get("prazo_recebimento", "")).replace(" ", "").upper()
        for bandeira in BANDEIRAS_PADRAO:
            taxa = row.get(bandeira)
            if pd.isna(taxa) or taxa == "":
                continue
            try:
                taxa_num = float(str(taxa).replace(",", "."))
            except ValueError:
                continue
            registros.append(
                {
                    "canal": canal,
                    "bandeira": bandeira,
                    "parcela_de": parcela_de,
                    "parcela_ate": parcela_ate,
                    "mdr": round(taxa_num, 4),
                    "prazo_recebimento": prazo,
                    "taxa_antecipacao": taxa_antecipacao,
                }
            )
    return pd.DataFrame(registros)


def _normalizar_modalidade(texto: str) -> str:
    texto = texto.lower()
    if "deb" in texto:
        return "DEBITO"
    if "avista" in texto or "a vista" in texto:
        return "CREDITO_AVISTA"
    if "2" in texto and "6" in texto:
        return "CREDITO_2A6X"
    if "7" in texto and "12" in texto:
        return "CREDITO_7A12X"
    if "13" in texto or "21" in texto:
        return "CREDITO_13A21X"
    if "credito" in texto or "crédito" in texto:
        return "CREDITO_AVISTA"
    return ""


def _faixa_parcelas(canal: str) -> Tuple[int, int]:
    if canal == "DEBITO":
        return 1, 1
    if canal == "CREDITO_AVISTA":
        return 1, 1
    if canal == "CREDITO_2A6X":
        return 2, 6
    if canal == "CREDITO_7A12X":
        return 7, 12
    if canal == "CREDITO_13A21X":
        return 13, 21
    return 1, 1


def gerar_hash_plano(df: pd.DataFrame, taxa_antecipacao: float = None) -> str:
    if df.empty:
        return ""
    df_ord = df.sort_values(by=["canal", "bandeira", "parcela_de", "parcela_ate"]).fillna("")
    linhas = []
    for _, row in df_ord.iterrows():
        linha = "|".join(
            [
                row["canal"],
                row["bandeira"],
                str(int(row["parcela_de"])),
                str(int(row["parcela_ate"])),
                f"{float(row['mdr']):.4f}",
                row.get("prazo_recebimento", ""),
                "" if taxa_antecipacao is None else f"{float(taxa_antecipacao):.4f}",
            ]
        )
        linhas.append(linha)
    payload = "\n".join(linhas)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def carregar_base_excel(path: str = DEFAULT_EXCEL_PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        _criar_base_excel(path)
    try:
        df = pd.read_excel(path, sheet_name="BASE_PLANOS")
    except ValueError:
        _criar_base_excel(path)
        df = pd.read_excel(path, sheet_name="BASE_PLANOS")
    return df


def _criar_base_excel(path: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "BASE_PLANOS"
    ws.append(
        [
            "plan_name",
            "canal",
            "bandeira",
            "parcela_de",
            "parcela_ate",
            "mdr",
            "prazo_recebimento",
            "taxa_antecipacao",
            "hash_plano",
            "data_criacao",
        ]
    )
    wb.save(path)


def comparar_com_base(hash_plano: str, base_df: pd.DataFrame) -> List[str]:
    if base_df.empty:
        return []
    hashes = (
        base_df.groupby("plan_name")["hash_plano"].first().reset_index().dropna(subset=["hash_plano"])
    )
    matches = hashes.loc[hashes["hash_plano"] == hash_plano, "plan_name"].tolist()
    return matches


def salvar_plano_na_base(df_normalizado: pd.DataFrame, plan_name: str, hash_plano: str, path: str):
    df_base = carregar_base_excel(path)
    now = datetime.utcnow().isoformat()
    df_novo = df_normalizado.copy()
    df_novo["plan_name"] = plan_name
    df_novo["hash_plano"] = hash_plano
    df_novo["data_criacao"] = now
    colunas = [
        "plan_name",
        "canal",
        "bandeira",
        "parcela_de",
        "parcela_ate",
        "mdr",
        "prazo_recebimento",
        "taxa_antecipacao",
        "hash_plano",
        "data_criacao",
    ]
    df_final = pd.concat([df_base, df_novo[colunas]], ignore_index=True)
    df_final.to_excel(path, sheet_name="BASE_PLANOS", index=False)


# --------------------------
# Interface Streamlit
# --------------------------
st.set_page_config(page_title="Leitor de Planos MDR", layout="wide")
st.title("Leitor e Comparador de Planos MDR")

st.sidebar.header("Configuração")
excel_path = st.sidebar.text_input("Caminho do Excel", value=DEFAULT_EXCEL_PATH)
st.sidebar.write(
    "Se o arquivo não existir, será criado automaticamente com a aba BASE_PLANOS."
)
tesseract_cmd = st.sidebar.text_input(
    "Caminho do binário do Tesseract",
    value=DEFAULT_TESSERACT_CMD,
    help="Ex.: /usr/bin/tesseract. Defina a variável de ambiente TESSERACT_CMD para alterar o padrão.",
)
pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
tesseract_ok = _tesseract_disponivel(tesseract_cmd)
if tesseract_ok:
    st.sidebar.success(f"Tesseract encontrado em: {tesseract_cmd}")
else:
    st.sidebar.error("Tesseract não encontrado. Instale o pacote tesseract-ocr ou aponte o caminho correto.")
    st.stop()

uploaded_file = st.file_uploader("Envie uma imagem de tabela (PNG, JPG, etc.)", type=["png", "jpg", "jpeg"])

if uploaded_file:
    st.subheader("Pré-visualização da imagem")
    st.image(uploaded_file, use_column_width=True)

    st.subheader("Resultado do OCR")
    with st.spinner("Lendo imagem e extraindo tabela..."):
        try:
            tabela_extraida, taxa_antecipacao = ler_imagem_e_extrair_tabela(uploaded_file)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
            st.stop()
    st.write("Taxa de antecipação detectada:", taxa_antecipacao if taxa_antecipacao is not None else "N/A")

    if tabela_extraida.empty:
        st.warning("Não foi possível encontrar uma tabela válida na imagem. Ajuste a imagem e tente novamente.")
    else:
        st.write("Edite valores se necessário antes de normalizar:")
        tabela_editada = st.data_editor(tabela_extraida, num_rows="dynamic")

        st.subheader("Tabela normalizada")
        tabela_normalizada = normalizar_tabela(tabela_editada, taxa_antecipacao)
        st.dataframe(tabela_normalizada)

        hash_plano = gerar_hash_plano(tabela_normalizada, taxa_antecipacao)
        st.code(f"Hash do plano: {hash_plano}")

        base_df = carregar_base_excel(excel_path)
        planos_existentes = comparar_com_base(hash_plano, base_df)

        if planos_existentes:
            st.success("Este plano já existe na base.")
            plano_escolhido = st.selectbox("Selecione um plano", planos_existentes)
            if st.button("Usar plano existente"):
                st.info(f"Plano {plano_escolhido} selecionado. Nenhuma gravação necessária.")
        else:
            st.info("Plano não encontrado na base. Salve como novo.")
            novo_nome = st.text_input("Nome do novo plano (ex: PADRAO_2_89_DPLUS30)")
            if st.button("Salvar plano na base"):
                if not novo_nome:
                    st.error("Informe um nome para o plano.")
                elif tabela_normalizada.empty:
                    st.error("Tabela normalizada vazia. Não há dados para salvar.")
                else:
                    try:
                        salvar_plano_na_base(tabela_normalizada, novo_nome, hash_plano, excel_path)
                        st.success(f"Plano {novo_nome} salvo com sucesso em {excel_path}.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Erro ao salvar plano: {exc}")
else:
    st.info("Envie uma imagem para começar.")

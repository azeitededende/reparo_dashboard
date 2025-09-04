# dashboard_reparos.py

# ======================== IMPORTS ========================
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from io import BytesIO

# ======================== CONFIG & ESTILO ========================
# Configura a página do Streamlit (título, ícone, layout, barra lateral expandida)
st.set_page_config(page_title="Controle de Reparos", page_icon="⚒️", layout="wide", initial_sidebar_state="expanded")

# CSS customizado para esconder alguns elementos padrão do Streamlit e aplicar estilos
HIDE = """
<style>
div[data-testid="stStatusWidget"], div[data-testid="stDecoration"] { visibility: hidden; height:0; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: 0.5rem; }
.small-muted { font-size: 0.85rem; opacity: 0.8; }
.overdue { background-color: #ffebe9 !important; }  /* cor de fundo para itens atrasados */
.soon { background-color: #fff8e1 !important; }     /* cor de fundo para itens próximos do prazo */
</style>
"""
st.markdown(HIDE, unsafe_allow_html=True)  # Aplica o CSS acima

# ======================== FUNÇÕES AUXILIARES ========================

@st.cache_data(show_spinner=False)  # Cache para não reler o Excel toda hora
def carregar_dados(path: str) -> pd.DataFrame:
    """
    Lê o arquivo Excel com os reparos, renomeia colunas problemáticas,
    trata datas, converte tipos e gera colunas derivadas (prazo, atraso, etc).
    """
    # Lista das colunas que queremos manter
    colunas_importantes = [
        "Status","Sit","Prefixo","Orç/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Grupo","Enviar até","Retornar até",
        "Motivo","Condição","Qtdade"
    ]

    # Lê toda a aba "Worksheet" (mesmo que as colunas estejam com nome estranho)
    df = pd.read_excel(path, sheet_name="Worksheet")

    # Mapeia nomes estranhos para os corretos (problemas de encoding)
    mapa_renome = {
        "Or?/OS": "Orç/OS",
        "Orc/OS": "Orç/OS",
        "Enviar at?": "Enviar até",
        "Retornar at?": "Retornar até",
        "Condi??o": "Condição",
        "Condicao": "Condição",
    }
    df = df.rename(columns=mapa_renome)

    # Mantém apenas as colunas importantes que realmente existem no arquivo
    keep = [c for c in colunas_importantes if c in df.columns]
    df = df[keep].copy()

    # Converte colunas de data para datetime
    for col in ["Enviar até", "Retornar até"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    # Remove espaços extras em todas as colunas de texto
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()

    # Converte coluna de quantidade para inteiro
    if "Qtdade" in df.columns:
        df["Qtdade"] = pd.to_numeric(df["Qtdade"], errors="coerce").fillna(0).astype(int)

    # Cria colunas derivadas para controlar prazos
    hoje = pd.Timestamp(datetime.now().date())
    if "Retornar até" in df.columns:
        df["Dias para devolver"] = (df["Retornar até"] - hoje).dt.days
        df["Em atraso"] = df["Dias para devolver"].apply(lambda x: True if pd.notna(x) and x < 0 else False)
        df["Vence em 7 dias"] = df["Dias para devolver"].apply(lambda x: True if pd.notna(x) and 0 <= x <= 7 else False)
    else:
        # Se não existir coluna "Retornar até", cria colunas vazias
        df["Dias para devolver"] = pd.NA
        df["Em atraso"] = False
        df["Vence em 7 dias"] = False

    # Exporta CSV atualizado (opcional)
    out = df.copy()
    out.to_csv("reparo_atual_csv.csv", sep=";", index=False, encoding="utf-8")

    return df


def download_df(df: pd.DataFrame, filename: str = "reparos_filtrado.csv"):
    """
    Gera botão para baixar o dataframe filtrado em formato CSV.
    """
    buffer = BytesIO()
    df.to_csv(buffer, index=False, sep=";", encoding="utf-8")
    st.download_button("⬇️ Baixar CSV filtrado", buffer.getvalue(), file_name=filename, mime="text/csv")


def estilo_tabela(df: pd.DataFrame):
    """
    Aplica estilo às linhas da tabela: vermelho para atrasados, amarelo para próximos.
    """
    def highlight_row(row):
        if row.get("Em atraso", False):
            return ["overdue"] * len(row)  # Aplica classe CSS overdue
        if row.get("Vence em 7 dias", False):
            return ["soon"] * len(row)     # Aplica classe CSS soon
        return [""] * len(row)            # Linha normal

    return df.style.apply(highlight_row, axis=1)


# ======================== SIDEBAR (FILTROS) ========================
st.sidebar.title("Filtros")

# Campo para digitar o caminho do Excel
path = st.sidebar.text_input("Arquivo Excel", value="reparo_atual.xlsx")

# Carrega os dados
df = carregar_dados(path)

# Função auxiliar para gerar opções de filtro baseadas nos valores do DataFrame
def options(col):
    return ["(Todos)"] + sorted([x for x in df[col].dropna().astype(str).unique()]) if col in df.columns else []

# Filtros por Status, Situação, Grupo, Prefixo e busca
f_status = st.sidebar.selectbox("Status", options("Status"))
f_sit    = st.sidebar.selectbox("Situação (Sit)", options("Sit"))
f_grupo  = st.sidebar.selectbox("Grupo", options("Grupo"))
f_prefixo= st.sidebar.text_input("Prefixo (contém)")
busca    = st.sidebar.text_input("Busca livre (qualquer coluna)")

# Filtro para escolher quais colunas exibir
colunas_mostrar = st.sidebar.multiselect(
    "Colunas visíveis",
    options=list(df.columns),
    default=[c for c in ["Status","Sit","Prefixo","Orç/OS","Item","P/N Compras","Retornar até","Dias para devolver","Em atraso","Qtdade"] if c in df.columns]
)

# Filtro de intervalo de datas baseado em "Retornar até"
if "Retornar até" in df.columns:
    min_d = pd.to_datetime(df["Retornar até"]).min()
    max_d = pd.to_datetime(df["Retornar até"]).max()
else:
    min_d = max_d = None

if pd.notna(min_d) and pd.notna(max_d):
    date_range = st.sidebar.date_input("Janela de 'Retornar até'", value=(min_d.date(), max_d.date()))
else:
    date_range = None

# Checkboxes extras
st.sidebar.markdown("---")
somente_atraso = st.sidebar.checkbox("Somente atrasados", value=False)
somente_7dias  = st.sidebar.checkbox("Somente que vencem em 7 dias", value=False)

# Opção de ordenação
st.sidebar.markdown("---")
ordem = st.sidebar.selectbox("Ordenar por", [c for c in ["Em atraso","Dias para devolver","Retornar até","Prefixo","Status","Sit","Grupo","Item"] if c in df.columns])


# ======================== APLICA FILTROS ========================
df_f = df.copy()

# Filtros condicionais (aplicados apenas se o usuário selecionar algo)
if f_status != "(Todos)" and "Status" in df_f.columns:
    df_f = df_f[df_f["Status"].astype(str) == f_status]

if f_sit != "(Todos)" and "Sit" in df_f.columns:
    df_f = df_f[df_f["Sit"].astype(str) == f_sit]

if f_grupo != "(Todos)" and "Grupo" in df_f.columns:
    df_f = df_f[df_f["Grupo"].astype(str) == f_grupo]

if f_prefixo and "Prefixo" in df_f.columns:
    df_f = df_f[df_f["Prefixo"].astype(str).str.contains(f_prefixo, case=False, na=False)]

if date_range and "Retornar até" in df_f.columns and len(date_range) == 2:
    ini, fim = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)
    df_f = df_f[(df_f["Retornar até"] >= ini) & (df_f["Retornar até"] < fim)]

if busca:
    txt = busca.strip().lower()
    mask = pd.Series(False, index=df_f.index)
    for col in df_f.columns:
        mask |= df_f[col].astype(str).str.lower().str.contains(txt, na=False)
    df_f = df_f[mask]

if somente_atraso and "Em atraso" in df_f.columns:
    df_f = df_f[df_f["Em atraso"] == True]

if somente_7dias and "Vence em 7 dias" in df_f.columns:
    df_f = df_f[df_f["Vence em 7 dias"] == True]

# Ordenação final
if ordem in df_f.columns:
    df_f = df_f.sort_values(by=[ordem, "Retornar até" if "Retornar até" in df_f.columns else ordem], ascending=[False if ordem=="Em atraso" else True, True])


# ======================== HEADER & KPIs ========================
st.title("⚒️ Controle de Reparos")

# KPIs (indicadores principais)
col_k1, col_k2, col_k3, col_k4 = st.columns(4)
total_itens = len(df_f)
atrasados = int(df_f["Em atraso"].sum()) if "Em atraso" in df_f.columns else 0
vence_7 = int(df_f["Vence em 7 dias"].sum()) if "Vence em 7 dias" in df_f.columns else 0
qtd_total = int(df_f["Qtdade"].sum()) if "Qtdade" in df_f.columns else total_itens

# Mostra os números em blocos
col_k1.metric("Itens filtrados", f"{total_itens}")
col_k2.metric("Em atraso", f"{atrasados}")
col_k3.metric("Vencem em 7 dias", f"{vence_7}")
col_k4.metric("Qtdade total (soma)", f"{qtd_total}")

# Última atualização
st.markdown(f"<span class='small-muted'>Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</span>", unsafe_allow_html=True)
st.markdown("---")


# ======================== ABAS ========================
tab1, tab2, tab3 = st.tabs(["📋 Itens", "📊 Agrupamentos", "📈 Tendências"])

# --- Aba 1: Itens em lista ---
with tab1:
    st.subheader("Lista de itens")
    if colunas_mostrar:
        mostrar = [c for c in colunas_mostrar if c in df_f.columns]
    else:
        mostrar = df_f.columns.tolist()

    # Mostra a tabela com estilos aplicados
    st.dataframe(estilo_tabela(df_f[mostrar]), use_container_width=True)
    download_df(df_f[mostrar])  # Botão de exportar CSV

# --- Aba 2: Agrupamentos ---
with tab2:
    # Gráficos por Status
    if "Status" in df_f.columns:
        st.subheader("Distribuição por Status")
        st.bar_chart(df_f["Status"].value_counts().sort_values(ascending=False))

    # Dois gráficos lado a lado
    col1, col2 = st.columns(2)
    with col1:
        if "Sit" in df_f.columns:
            st.subheader("Distribuição por Sit")
            st.bar_chart(df_f["Sit"].value_counts().sort_values(ascending=False))
    with col2:
        if "Grupo" in df_f.columns:
            st.subheader("Distribuição por Grupo")
            st.bar_chart(df_f["Grupo"].value_counts().sort_values(ascending=False))

    # Tabela pivô Prefixo x Sit
    if all(c in df_f.columns for c in ["Prefixo", "Sit"]):
        st.subheader("Tabela por Prefixo x Sit")
        piv = pd.pivot_table(
            df_f,
            index="Prefixo",
            columns="Sit",
            values="Item" if "Item" in df_f.columns else "Prefixo",
            aggfunc="count",
            fill_value=0
        )
        st.dataframe(piv, use_container_width=True)

# --- Aba 3: Tendências ---
with tab3:
    st.subheader("Acompanhamento de prazos")

    # Distribuição por buckets de prazo
    if "Dias para devolver" in df_f.columns:
        buckets = pd.cut(
            df_f["Dias para devolver"],
            bins=[-9999, -1, 0, 7, 30, 9999],
            labels=["Atrasado", "Hoje", "≤7 dias", "≤30 dias", ">30 dias"]
        )
        cont = buckets.value_counts().reindex(["Atrasado","Hoje","≤7 dias","≤30 dias",">30 dias"]).fillna(0).astype(int)
        st.bar_chart(cont)

    # Série temporal (quantidade de itens por dia de "Retornar até")
    if "Retornar até" in df_f.columns:
        serie = df_f.dropna(subset=["Retornar até"]).groupby(df_f["Retornar até"].dt.date).size()
        if not serie.empty:
            st.line_chart(serie)

# ======================== RODAPÉ ========================
st.markdown("---")
st.caption("Use os filtros na lateral para focar em um Grupo/Prefixo específico e clique em ⬇️ para exportar o resultado.")

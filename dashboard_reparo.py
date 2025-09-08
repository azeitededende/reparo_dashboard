# ======================== IMPORTS ========================
import pandas as pd
import streamlit as st
from datetime import datetime
from io import BytesIO
import os, unicodedata, re

# ======================== CONFIG & ESTILO ========================
st.set_page_config(
    page_title="Controle de Reparos",
    page_icon="⚒️",
    layout="wide",
    initial_sidebar_state="expanded"
)

HIDE = """
<style>
div[data-testid="stStatusWidget"], div[data-testid="stDecoration"] { visibility: hidden; height:0; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: 0.5rem; }
.small-muted { font-size: 0.85rem; opacity: 0.8; }
</style>
"""
st.markdown(HIDE, unsafe_allow_html=True)

# ======================== FUNÇÕES AUXILIARES ========================

@st.cache_data(show_spinner=False)
def carregar_dados(path: str) -> pd.DataFrame:
    """Lê o Excel (xls/xlsx/xlsb), normaliza colunas, trata datas e gera colunas derivadas."""

    # engine por extensão
    engine = None
    if isinstance(path, str):
        low = path.lower()
        if low.endswith(".xlsb"):
            engine = "pyxlsb"
        elif low.endswith(".xlsx"):
            engine = "openpyxl"
        elif low.endswith(".xls"):
            engine = "xlrd"

    # tenta aba Worksheet ou cai na primeira
    try:
        df = pd.read_excel(path, sheet_name="Worksheet", engine=engine)
    except Exception:
        xls = pd.ExcelFile(path, engine=engine)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

    # colunas de interesse
    colunas_importantes = [
        "Status","Sit","Prefixo","Orç/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Grupo","Enviar até","Retornar até",
        "Motivo","Condição","Qtdade"
    ]

    # renomeia casos comuns
    mapa_renome = {
        "Or?/OS": "Orç/OS", "Orc/OS": "Orç/OS",
        "Enviar at?": "Enviar até", "Retornar at?": "Retornar até",
        "Condi??o": "Condição", "Condicao": "Condição",
    }
    df = df.rename(columns=mapa_renome)

    # normaliza nomes
    def _norm(s):
        s = str(s)
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", s).strip()

    norm_cols = {c: _norm(c) for c in df.columns}
    alvo_norm = {a: _norm(a) for a in colunas_importantes}
    ren_extra = {}
    for col_atual, n_atual in norm_cols.items():
        for alvo, n_alvo in alvo_norm.items():
            if n_atual == n_alvo and col_atual != alvo:
                ren_extra[col_atual] = alvo
    if ren_extra:
        df = df.rename(columns=ren_extra)

    # mantém apenas colunas válidas
    keep = [c for c in colunas_importantes if c in df.columns]
    df = df[keep].copy()

    # datas
    for col in ["Enviar até", "Retornar até"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    # strip de textos
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()

    # qtdade
    if "Qtdade" in df.columns:
        df["Qtdade"] = pd.to_numeric(df["Qtdade"], errors="coerce").fillna(0).astype(int)

    # derivadas de prazo
    hoje = pd.Timestamp(datetime.now().date())
    if "Retornar até" in df.columns:
        df["Dias para devolver"] = (df["Retornar até"] - hoje).dt.days
        df["Em atraso"] = df["Dias para devolver"].apply(lambda x: bool(pd.notna(x) and x < 0))
        df["Vence em 7 dias"] = df["Dias para devolver"].apply(lambda x: bool(pd.notna(x) and 0 <= x <= 7))
    else:
        df["Dias para devolver"] = pd.NA
        df["Em atraso"] = False
        df["Vence em 7 dias"] = False

    # exporta CSV auxiliar
    try:
        df.to_csv("reparo_atual_csv.csv", sep=";", index=False, encoding="utf-8")
    except Exception:
        pass

    return df


def download_df(df: pd.DataFrame, filename: str = "reparos_filtrado.csv"):
    buffer = BytesIO()
    df.to_csv(buffer, index=False, sep=";", encoding="utf-8")
    st.download_button("⬇️ Baixar CSV filtrado", buffer.getvalue(), file_name=filename, mime="text/csv")


def estilo_tabela(df: pd.DataFrame):
    """Aplica cores inline via Styler."""
    def highlight_row(row):
        if row.get("Em atraso", False):
            return ["background-color: #ffebe9"] * len(row)
        if row.get("Vence em 7 dias", False):
            return ["background-color: #fff8e1"] * len(row)
        return [""] * len(row)
    return df.style.apply(highlight_row, axis=1)

# ======================== SIDEBAR ========================
st.sidebar.title("Filtros")
path = st.sidebar.text_input("Arquivo Excel", value="reparo_atual.xlsx")
df = carregar_dados(path)

def options(col): return ["(Todos)"] + sorted([x for x in df[col].dropna().astype(str).unique()]) if col in df.columns else []

f_status  = st.sidebar.selectbox("Status", options("Status"))
f_sit     = st.sidebar.selectbox("Situação (Sit)", options("Sit"))
f_grupo   = st.sidebar.selectbox("Grupo", options("Grupo"))
f_prefixo = st.sidebar.text_input("Prefixo (contém)")
busca     = st.sidebar.text_input("Busca livre")

colunas_mostrar = st.sidebar.multiselect(
    "Colunas visíveis",
    options=list(df.columns),
    default=[c for c in ["Status","Sit","Prefixo","Orç/OS","Item","P/N Compras","Retornar até","Dias para devolver","Em atraso","Qtdade"] if c in df.columns]
)

if "Retornar até" in df.columns:
    min_d, max_d = df["Retornar até"].min(), df["Retornar até"].max()
else:
    min_d = max_d = None
date_range = st.sidebar.date_input("Janela de 'Retornar até'", value=(min_d.date(), max_d.date())) if pd.notna(min_d) and pd.notna(max_d) else None

st.sidebar.markdown("---")
somente_atraso = st.sidebar.checkbox("Somente atrasados", False)
somente_7dias  = st.sidebar.checkbox("Somente que vencem em 7 dias", False)

st.sidebar.markdown("---")
ordem = st.sidebar.selectbox("Ordenar por", [c for c in ["Em atraso","Dias para devolver","Retornar até","Prefixo","Status","Sit","Grupo","Item"] if c in df.columns])

# ======================== FILTROS ========================
df_f = df.copy()
if f_status != "(Todos)" and "Status" in df_f: df_f = df_f[df_f["Status"] == f_status]
if f_sit    != "(Todos)" and "Sit" in df_f:    df_f = df_f[df_f["Sit"] == f_sit]
if f_grupo  != "(Todos)" and "Grupo" in df_f:  df_f = df_f[df_f["Grupo"] == f_grupo]
if f_prefixo and "Prefixo" in df_f: df_f = df_f[df_f["Prefixo"].str.contains(f_prefixo, case=False, na=False)]
if date_range and "Retornar até" in df_f and len(date_range) == 2:
    ini, fim = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)
    df_f = df_f[(df_f["Retornar até"] >= ini) & (df_f["Retornar até"] < fim)]
if busca:
    txt = busca.strip().lower()
    mask = pd.Series(False, index=df_f.index)
    for col in df_f.columns:
        mask |= df_f[col].astype(str).str.lower().str.contains(txt, na=False)
    df_f = df_f[mask]
if somente_atraso and "Em atraso" in df_f: df_f = df_f[df_f["Em atraso"]]
if somente_7dias and "Vence em 7 dias" in df_f: df_f = df_f[df_f["Vence em 7 dias"]]

if ordem in df_f: df_f = df_f.sort_values(by=[ordem, "Retornar até" if "Retornar até" in df_f else ordem],
                                          ascending=[False if ordem=="Em atraso" else True, True])

# ======================== HEADER & KPIs ========================
st.title("⚒️ Controle de Reparos")

col_k1, col_k2, col_k3, col_k4 = st.columns(4)
col_k1.metric("Itens filtrados", f"{len(df_f)}")
col_k2.metric("Em atraso", f"{int(df_f['Em atraso'].sum()) if 'Em atraso' in df_f else 0}")
col_k3.metric("Vencem em 7 dias", f"{int(df_f['Vence em 7 dias'].sum()) if 'Vence em 7 dias' in df_f else 0}")
col_k4.metric("Qtdade total (soma)", f"{int(df_f['Qtdade'].sum()) if 'Qtdade' in df_f else len(df_f)}")

st.markdown(f"<span class='small-muted'>Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</span>", unsafe_allow_html=True)
st.markdown("---")

# ======================== ABAS ========================
tab1, tab2, tab3 = st.tabs(["📋 Itens", "📊 Agrupamentos", "📈 Tendências"])

with tab1:
    st.subheader("Lista de itens")
    mostrar = [c for c in colunas_mostrar if c in df_f.columns] or df_f.columns.tolist()
    st.dataframe(estilo_tabela(df_f[mostrar]), use_container_width=True)
    download_df(df_f[mostrar])

with tab2:
    if "Status" in df_f: st.subheader("Distribuição por Status"); st.bar_chart(df_f["Status"].value_counts())
    col1, col2 = st.columns(2)
    with col1:
        if "Sit" in df_f: st.subheader("Distribuição por Sit"); st.bar_chart(df_f["Sit"].value_counts())
    with col2:
        if "Grupo" in df_f: st.subheader("Distribuição por Grupo"); st.bar_chart(df_f["Grupo"].value_counts())
    if all(c in df_f for c in ["Prefixo","Sit"]):
        st.subheader("Tabela por Prefixo x Sit")
        piv = pd.pivot_table(df_f, index="Prefixo", columns="Sit",
                             values="Item" if "Item" in df_f else "Prefixo",
                             aggfunc="count", fill_value=0)
        st.dataframe(piv, use_container_width=True)

with tab3:
    st.subheader("Acompanhamento de prazos")
    if "Dias para devolver" in df_f:
        buckets = pd.cut(df_f["Dias para devolver"], bins=[-9999,-1,0,7,30,9999],
                         labels=["Atrasado","Hoje","≤7 dias","≤30 dias",">30 dias"])
        st.bar_chart(buckets.value_counts().reindex(["Atrasado","Hoje","≤7 dias","≤30 dias",">30 dias"]).fillna(0).astype(int))
    if "Retornar até" in df_f:
        serie = df_f.dropna(subset=["Retornar até"]).groupby(df_f["Retornar até"].dt.date).size()
        if not serie.empty: st.line_chart(serie)

# ======================== RODAPÉ ========================
st.markdown("---")
st.caption("Use os filtros na lateral e clique em ⬇️ para exportar o resultado.")

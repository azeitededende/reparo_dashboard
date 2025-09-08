# ======================== IMPORTS ========================
import os
import re
import unicodedata
from datetime import datetime
from io import BytesIO

import numpy as np
import pandas as pd
import streamlit as st

# ======================== CONFIG & TEMA ========================
st.set_page_config(
    page_title="Controle de Reparos",
    page_icon="⚒️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS leve (sem quebrar st.dataframe)
BASE_CSS = """
<style>
/* limpa ruídos visuais */
div[data-testid="stStatusWidget"], div[data-testid="stDecoration"] { visibility: hidden; height:0; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: .5rem; }

/* tipografia e espaçamentos */
h1, h2, h3 { letter-spacing: .2px; }
.small-muted { font-size: 0.85rem; opacity: 0.8; }

/* chips */
.badge { display:inline-block; padding:.25rem .5rem; border-radius:999px; font-size:.78rem; margin-right:.35rem; }
.badge-gray { background:#f3f4f6; border:1px solid #e5e7eb; }
.badge-blue { background:#e8f1ff; border:1px solid #c9ddff; }
.badge-amber { background:#fff4d6; border:1px solid #ffe4a6; }
.badge-red { background:#ffe6e3; border:1px solid #ffcdc6; }

/* cards de KPIs */
.kpi { border:1px solid #eee; border-radius:12px; padding:14px 16px; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,.05); }
.kpi .kpi-title { font-size:.85rem; color:#6b7280; margin-bottom:.35rem; }
.kpi .kpi-value { font-size:1.6rem; font-weight:700; }

/* tabela: manter scroll agradável */
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border:1px solid #eee; }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)

# ======================== UTILS ========================
def _norm(s: str) -> str:
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip()

def _choose_engine(path: str | BytesIO | None) -> str | None:
    if isinstance(path, str):
        low = path.lower()
        if low.endswith(".xlsb"):
            return "pyxlsb"
        if low.endswith(".xlsx"):
            return "openpyxl"
        if low.endswith(".xls"):
            return "xlrd"
    return None

# ======================== LOAD ========================
@st.cache_data(show_spinner=False)
def carregar_dados(path: str | BytesIO) -> pd.DataFrame:
    """Lê xls/xlsx/xlsb, normaliza colunas, datas e cria derivadas."""
    engine = _choose_engine(path)

    # tenta aba padrão; se falhar, usa a 1ª
    try:
        df = pd.read_excel(path, sheet_name="Worksheet", engine=engine)
    except Exception:
        xls = pd.ExcelFile(path, engine=engine)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

    # colunas alvo
    colunas_importantes = [
        "Status","Sit","Prefixo","Orç/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Grupo","Enviar até","Retornar até",
        "Motivo","Condição","Qtdade"
    ]

    # renomes comuns
    mapa_renome = {
        "Or?/OS": "Orç/OS", "Orc/OS": "Orç/OS",
        "Enviar at?": "Enviar até", "Retornar at?": "Retornar até",
        "Condi??o": "Condição", "Condicao": "Condição",
    }
    df = df.rename(columns=mapa_renome)

    # aproximar por nomes normalizados
    norm_cols = {c: _norm(c) for c in df.columns}
    alvo_norm = {a: _norm(a) for a in colunas_importantes}
    ren_extra = {}
    for col_atual, n_atual in norm_cols.items():
        for alvo, n_alvo in alvo_norm.items():
            if n_atual == n_alvo and col_atual != alvo:
                ren_extra[col_atual] = alvo
    if ren_extra:
        df = df.rename(columns=ren_extra)

    # manter só o que existe
    keep = [c for c in colunas_importantes if c in df.columns]
    df = df[keep].copy()

    # datas
    for col in ["Enviar até", "Retornar até"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    # textos
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()

    # quantidade
    if "Qtdade" in df.columns:
        df["Qtdade"] = pd.to_numeric(df["Qtdade"], errors="coerce").fillna(0).astype(int)

    # derivadas
    hoje = pd.Timestamp(datetime.now().date())
    if "Retornar até" in df.columns:
        df["Dias para devolver"] = (df["Retornar até"] - hoje).dt.days
        df["Em atraso"] = df["Dias para devolver"].apply(lambda x: bool(pd.notna(x) and x < 0))
        df["Vence em 7 dias"] = df["Dias para devolver"].apply(lambda x: bool(pd.notna(x) and 0 <= x <= 7))
        df["Sem data"] = df["Retornar até"].isna()
    else:
        df["Dias para devolver"] = pd.NA
        df["Em atraso"] = False
        df["Vence em 7 dias"] = False
        df["Sem data"] = True

    # export auxiliar (sem travar se não puder escrever)
    try:
        df.to_csv("reparo_atual_csv.csv", sep=";", index=False, encoding="utf-8")
    except Exception:
        pass

    return df

def download_df(df: pd.DataFrame, filename: str = "reparos_filtrado.csv"):
    buf = BytesIO()
    df.to_csv(buf, index=False, sep=";", encoding="utf-8")
    st.download_button("⬇️ Baixar CSV filtrado", buf.getvalue(), file_name=filename, mime="text/csv")

def download_excel(df: pd.DataFrame, filename: str = "reparos_filtrado.xlsx"):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Filtrado")
    st.download_button("⬇️ Baixar Excel filtrado", buf.getvalue(), file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ======================== STYLER ROBUSTO ========================
def estilo_tabela(df: pd.DataFrame):
    """Cores por linha (atraso, proximidade) + gradiente nos dias. Fallback no caller."""
    sty = df.style

    # gradient em Dias para devolver, quando existir
    if "Dias para devolver" in df.columns:
        # substitui NaN por grande positivo só para normalizar, sem alterar df
        serie = df["Dias para devolver"].astype("float")
        sty = sty.background_gradient(
            subset=["Dias para devolver"],
            cmap="RdYlGn_r",  # não define cor fixa (mapa padrão do matplotlib)
            vmin=np.nanmin(serie.values) if np.isfinite(serie.values).any() else 0,
            vmax=np.nanmax(serie.values) if np.isfinite(serie.values).any() else 0,
        )

    # highlight por linha
    def highlight_row(row):
        if row.get("Em atraso", False):
            return ["background-color: #ffe6e3"] * len(row)  # vermelho claro
        if row.get("Vence em 7 dias", False):
            return ["background-color: #fff4d6"] * len(row)  # amarelo claro
        return [""] * len(row)

    sty = sty.apply(highlight_row, axis=1)
    return sty

# ======================== SIDEBAR (FILTROS) ========================
st.sidebar.title("📌 Filtros")

# Origem dos dados
with st.sidebar.expander("Fonte de dados", expanded=True):
    up = st.file_uploader("Enviar arquivo (.xlsx/.xls/.xlsb)", type=["xlsx","xls","xlsb"])
    if up is not None:
        path = BytesIO(up.read())
    else:
        # caminho padrão (deploy com arquivo no container)
        path = st.text_input("Ou caminho local do Excel", value="reparo_atual.xlsx")

df = carregar_dados(path)

# Vistas rápidas
st.sidebar.markdown("### Vistas rápidas")
vista = st.sidebar.radio(
    label="Seleção",
    options=["Todos os itens", "Atrasados", "Próx. 7 dias", "Sem data"],
    index=0,
)

# Filtros tradicionais
f_status  = st.sidebar.selectbox("Status", ["(Todos)"] + sorted(df["Status"].dropna().astype(str).unique()) if "Status" in df else ["(Todos)"])
f_sit     = st.sidebar.selectbox("Situação (Sit)", ["(Todos)"] + sorted(df["Sit"].dropna().astype(str).unique()) if "Sit" in df else ["(Todos)"])
f_grupo   = st.sidebar.selectbox("Grupo", ["(Todos)"] + sorted(df["Grupo"].dropna().astype(str).unique()) if "Grupo" in df else ["(Todos)"])
f_prefixo = st.sidebar.text_input("Prefixo (contém)")
busca     = st.sidebar.text_input("Busca livre (qualquer coluna)")

# Datas (opcional)
st.sidebar.markdown("---")
inclui_sem_data = st.sidebar.checkbox("Incluir itens sem data", value=True)
habilitar_filtro_datas = st.sidebar.checkbox("Filtrar por 'Retornar até'", value=False)

date_range = None
if habilitar_filtro_datas and "Retornar até" in df.columns:
    min_d, max_d = df["Retornar até"].min(), df["Retornar até"].max()
    if pd.notna(min_d) and pd.notna(max_d):
        date_range = st.sidebar.date_input("Janela de 'Retornar até'", value=(min_d.date(), max_d.date()))
    else:
        st.sidebar.info("Não há datas válidas em 'Retornar até'.")

# Colunas visíveis
st.sidebar.markdown("---")
colunas_mostrar = st.sidebar.multiselect(
    "Colunas visíveis",
    options=list(df.columns),
    default=[c for c in ["Status","Sit","Prefixo","Orç/OS","Item","P/N Compras","Retornar até","Dias para devolver","Em atraso","Vence em 7 dias","Qtdade"] if c in df.columns]
)

# Ordenação
ordem = st.sidebar.selectbox(
    "Ordenar por",
    [c for c in ["Em atraso","Vence em 7 dias","Dias para devolver","Retornar até","Prefixo","Status","Sit","Grupo","Item","Qtdade"] if c in df.columns]
)
ordem_cresc = st.sidebar.toggle("Ordem crescente", value=False if ordem in ["Em atraso","Vence em 7 dias"] else True)

# Toggle de performance
st.sidebar.markdown("---")
usar_estilo = st.sidebar.checkbox("Aplicar destaque visual na tabela", value=True)

# ======================== FILTRAGEM ========================
df_f = df.copy()

# Vistas rápidas
if vista == "Atrasados" and "Em atraso" in df_f:
    df_f = df_f[df_f["Em atraso"]]
elif vista == "Próx. 7 dias" and "Vence em 7 dias" in df_f:
    df_f = df_f[df_f["Vence em 7 dias"]]
elif vista == "Sem data" and "Sem data" in df_f:
    df_f = df_f[df_f["Sem data"]]
# "Todos os itens" não restringe por data (ainda assim pode usar filtros abaixo)

# Filtros por campo
if f_status != "(Todos)" and "Status" in df_f: df_f = df_f[df_f["Status"].astype(str) == f_status]
if f_sit    != "(Todos)" and "Sit" in df_f:    df_f = df_f[df_f["Sit"].astype(str) == f_sit]
if f_grupo  != "(Todos)" and "Grupo" in df_f:  df_f = df_f[df_f["Grupo"].astype(str) == f_grupo]
if f_prefixo and "Prefixo" in df_f:            df_f = df_f[df_f["Prefixo"].astype(str).str.contains(f_prefixo, case=False, na=False)]

# Busca livre
if busca:
    txt = busca.strip().lower()
    mask = pd.Series(False, index=df_f.index)
    for col in df_f.columns:
        mask |= df_f[col].astype(str).str.lower().str.contains(txt, na=False)
    df_f = df_f[mask]

# Filtro por datas (opcional e NÃO obrigatório)
if habilitar_filtro_datas and date_range and "Retornar até" in df_f and len(date_range) == 2:
    ini, fim = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)
    mask_data = (df_f["Retornar até"] >= ini) & (df_f["Retornar até"] < fim)
    if inclui_sem_data and "Retornar até" in df_f:
        mask_data |= df_f["Retornar até"].isna()
    df_f = df_f[mask_data]
elif not inclui_sem_data and "Retornar até" in df_f:
    # quando NÃO quiser incluir sem data, remove-os
    df_f = df_f[~df_f["Retornar até"].isna()]

# Ordenação
if ordem in df_f.columns:
    # segunda chave consistente para estabilidade
    secund = "Retornar até" if ("Retornar até" in df_f.columns and ordem != "Retornar até") else None
    if secund:
        df_f = df_f.sort_values(by=[ordem, secund], ascending=[ordem_cresc, True])
    else:
        df_f = df_f.sort_values(by=[ordem], ascending=[ordem_cresc])

# ======================== HEADER & KPIs ========================
st.title("⚒️ Controle de Reparos")

# KPIs (estilo cards)
k1, k2, k3, k4, k5 = st.columns(5)
total_itens = len(df_f)
atrasados   = int(df_f["Em atraso"].sum()) if "Em atraso" in df_f else 0
prox7       = int(df_f["Vence em 7 dias"].sum()) if "Vence em 7 dias" in df_f else 0
sem_data    = int(df_f["Sem data"].sum()) if "Sem data" in df_f else 0
qtd_total   = int(df_f["Qtdade"].sum()) if "Qtdade" in df_f else total_itens

for col, title, value in [
    (k1,"Itens filtrados", total_itens),
    (k2,"Em atraso", atrasados),
    (k3,"Vencem em 7 dias", prox7),
    (k4,"Sem data", sem_data),
    (k5,"Qtdade total (soma)", qtd_total),
]:
    with col:
        st.markdown(f"""
        <div class="kpi">
            <div class="kpi-title">{title}</div>
            <div class="kpi-value">{value}</div>
        </div>
        """, unsafe_allow_html=True)

# Chips-resumo
st.markdown(
    f"""
    <div style="margin:.5rem 0 .75rem 0;">
      <span class="badge badge-blue">Vista: {vista}</span>
      <span class="badge badge-gray">Ordenado por: {ordem} {'↑' if ordem_cresc else '↓'}</span>
      <span class="badge badge-amber">{'Incluindo' if inclui_sem_data else 'Excluindo'} sem data</span>
      <span class="badge badge-gray">Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</span>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown("---")

# ======================== ABAS ========================
tab1, tab2, tab3 = st.tabs(["📋 Itens", "📊 Agrupamentos", "📈 Tendências"])

# --- Aba 1: Itens ---
with tab1:
    st.subheader("Lista de itens")

    if not colunas_mostrar:
        st.info("Selecione ao menos uma coluna para exibir nas opções da barra lateral.")
    else:
        mostrar = [c for c in colunas_mostrar if c in df_f.columns]
        if not mostrar:
            st.info("As colunas escolhidas não existem no resultado atual. Ajuste os filtros.")
        else:
            df_view = df_f[mostrar]
            # Fallback automático se Styler der erro (evita “tela branca”)
            try:
                if usar_estilo:
                    st.dataframe(estilo_tabela(df_view), use_container_width=True)
                else:
                    st.dataframe(df_view, use_container_width=True)
            except Exception as e:
                st.warning(f"Não foi possível aplicar o destaque visual ({type(e).__name__}). Exibindo tabela simples.")
                st.dataframe(df_view, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                download_df(df_view)
            with c2:
                if "openpyxl" in {pkg.key for pkg in __import__("pkgutil").iter_modules()}:
                    download_excel(df_view)
                else:
                    # evita erro se openpyxl não estiver no runtime
                    pass

# --- Aba 2: Agrupamentos ---
with tab2:
    cA, cB = st.columns(2)
    with cA:
        if "Status" in df_f.columns and not df_f.empty:
            st.subheader("Distribuição por Status")
            st.bar_chart(df_f["Status"].value_counts().sort_values(ascending=False))
    with cB:
        if "Grupo" in df_f.columns and not df_f.empty:
            st.subheader("Distribuição por Grupo")
            st.bar_chart(df_f["Grupo"].value_counts().sort_values(ascending=False))

    cC, cD = st.columns(2)
    with cC:
        if "Sit" in df_f.columns and not df_f.empty:
            st.subheader("Distribuição por Sit")
            st.bar_chart(df_f["Sit"].value_counts().sort_values(ascending=False))
    with cD:
        if all(c in df_f.columns for c in ["Prefixo","Sit"]) and not df_f.empty:
            st.subheader("Prefixo × Sit (contagem)")
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
    if "Dias para devolver" in df_f.columns and not df_f.empty:
        buckets = pd.cut(
            df_f["Dias para devolver"],
            bins=[-9999, -1, 0, 7, 30, 9999],
            labels=["Atrasado","Hoje","≤7 dias","≤30 dias",">30 dias"]
        )
        cont = buckets.value_counts().reindex(["Atrasado","Hoje","≤7 dias","≤30 dias",">30 dias"]).fillna(0).astype(int)
        st.bar_chart(cont)

    if "Retornar até" in df_f.columns:
        serie = df_f.dropna(subset=["Retornar até"]).groupby(df_f["Retornar até"].dt.date).size()
        if not serie.empty:
            st.line_chart(serie)
        else:
            st.info("Sem dados de 'Retornar até' para série temporal.")

# ======================== RODAPÉ ========================
st.markdown("---")
st.caption("Dica: Use as 'Vistas rápidas' para navegar entre cenários (atrasados, próximos 7 dias, sem data).")

# ======================== IMPORTS ========================
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

BASE_CSS = """
<style>
/* limpa ruídos */
div[data-testid="stStatusWidget"], div[data-testid="stDecoration"] { visibility: hidden; height:0; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: .5rem; }
h1, h2, h3 { letter-spacing: .2px; }

/* ===== Paleta base dos componentes (compatível com tema escuro) ===== */
:root {
  --card-bg: #ffffff;        /* fundo claro p/ cards e kpis */
  --card-fg: #111827;        /* texto escuro p/ garantir contraste */
  --muted:   #6b7280;
  --border:  #ececec;

  --badge-fg: #111827;
  --badge-gray-bg:  #f3f4f6; --badge-gray-bd:  #e5e7eb;
  --badge-blue-bg:  #e8f1ff; --badge-blue-bd:  #c9ddff;
  --badge-amber-bg: #fff4d6; --badge-amber-bd: #ffe4a6;
  --badge-red-bg:   #ffe6e3; --badge-red-bd:   #ffcdc6;
  --badge-green-bg: #e7f6ec; --badge-green-bd: #c9e8d2;

  --warn-bg: #fff9ea; --warn-bd: #ffe4a6;
  --danger-bg:#ffeceb; --danger-bd:#ffcdc6;
}

/* cards e kpis com cor de texto forçada (resolve “texto branco em fundo branco”) */
.kpi, .kpi * { color: var(--card-fg) !important; }
.card, .card * { color: var(--card-fg) !important; }

/* badges com texto escuro para manter leitura em tema dark */
.badge { color: var(--badge-fg) !important; }

/* ===== Badges ===== */
.badge { display:inline-block; padding:.25rem .55rem; border-radius:999px; font-size:.78rem; margin-right:.35rem; }
.badge-gray  { background:var(--badge-gray-bg);  border:1px solid var(--badge-gray-bd); }
.badge-blue  { background:var(--badge-blue-bg);  border:1px solid var(--badge-blue-bd); }
.badge-amber { background:var(--badge-amber-bg); border:1px solid var(--badge-amber-bd); }
.badge-red   { background:var(--badge-red-bg);   border:1px solid var(--badge-red-bd); }
.badge-green { background:var(--badge-green-bg); border:1px solid var(--badge-green-bd); }

/* ===== KPIs ===== */
.kpi {
  border:1px solid var(--border); border-radius:12px; padding:14px 16px; background:var(--card-bg);
  box-shadow:0 1px 2px rgba(0,0,0,.05);
}
.kpi .kpi-title { font-size:.85rem; color: var(--muted) !important; margin-bottom:.35rem; }
.kpi .kpi-value { font-size:1.6rem; font-weight:700; }

/* ===== Cards ===== */
.card {
  border:1px solid var(--border); border-radius:14px; padding:14px; background:var(--card-bg);
  box-shadow:0 1px 3px rgba(0,0,0,.06); display:flex; flex-direction:column; gap:.5rem; height:100%;
}
.card-header { display:flex; align-items:center; justify-content:space-between; gap:.5rem; }
.card-title { font-weight:700; font-size:1.02rem; }
.card-sub { color: var(--muted) !important; font-size:.86rem; }
.card-row { display:flex; flex-wrap:wrap; gap:.35rem .5rem; align-items:center; }
.card .muted { color: var(--muted) !important; font-size:.82rem; }

.card-danger { border-color: var(--danger-bd); background: linear-gradient(0deg, #fff, #fff), var(--danger-bg); }
.card-warn   { border-color: var(--warn-bd);   background: linear-gradient(0deg, #fff, #fff), var(--warn-bg); }

/* Chips de contexto e gráficos */
.context { margin:.5rem 0 .75rem 0; }
.small-muted { font-size: 0.85rem; opacity: 0.8; }
[data-testid="stVegaLiteChart"] { border-radius: 12px; overflow: hidden; border:1px solid var(--border); }
</style>
"""

st.markdown(BASE_CSS, unsafe_allow_html=True)

# ======================== HELPERS ========================
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

def parse_mixed_dates(series: pd.Series) -> pd.Series:
    """Parse seguro: ISO (YYYY-MM-DD) e demais com dayfirst=True, sem warnings."""
    s = series.astype(str).str.strip()
    idx = s.index
    out = pd.Series(pd.NaT, index=idx, dtype="datetime64[ns]")
    iso_mask = s.str.match(r"^\d{4}-\d{2}-\d{2}$")
    if iso_mask.any():
        out.loc[iso_mask] = pd.to_datetime(s.loc[iso_mask], format="%Y-%m-%d", errors="coerce")
    if (~iso_mask).any():
        out.loc[~iso_mask] = pd.to_datetime(s.loc[~iso_mask], dayfirst=True, errors="coerce")
    return out

def limpar_status(valor: str) -> str:
    """
    Regras de exibição do Status:
      - P.O (ou variações) + 'fechad' -> 'P.O Fechada'
      - P.O simples -> 'P.O'
      - 'não/nao/n?o comprad' -> 'Não comprado'
      - caso contrário, mantém original
    """
    if pd.isna(valor):
        return valor
    raw = str(valor).strip()
    n = _norm(raw).lower()
    has_po = bool(re.search(r"\b(?:p\s*\.?\s*o|po)\b", n))
    closed = "fechad" in n
    nao_comprado = ("nao comprad" in n) or ("não comprad" in raw.lower()) or ("n?o comprad" in raw.lower())
    if nao_comprado:
        return "Não comprado"
    if has_po and closed:
        return "P.O Fechada"
    if has_po:
        return "P.O"
    return raw

def normalizar_valores(df: pd.DataFrame) -> pd.DataFrame:
    """Correções pontuais de mojibake sem mexer no resto dos textos."""
    out = df.copy()
    # Normaliza Grupo -> 'Peças' quando vier 'pe?cas' ou 'pecas'
    if "Grupo" in out.columns:
        def fix_grupo(x):
            if pd.isna(x): return x
            s = str(x)
            if re.search(r"\bpe\?cas\b", s, flags=re.IGNORECASE) or re.search(r"\bpecas\b", _norm(s), flags=re.IGNORECASE):
                return "Peças"
            return s
        out["Grupo"] = out["Grupo"].apply(fix_grupo)
    return out

# ======================== LOAD ========================
@st.cache_data(show_spinner=False)
def carregar_dados(path: str | BytesIO) -> pd.DataFrame:
    """Lê xls/xlsx/xlsb, normaliza colunas, datas e cria derivadas de prazo + status limpo."""
    engine = _choose_engine(path)
    # tenta aba padrão; se falhar, usa a 1ª
    try:
        df = pd.read_excel(path, sheet_name="Worksheet", engine=engine)
    except Exception:
        xls = pd.ExcelFile(path, engine=engine)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

    colunas_importantes = [
        "Status","Sit","Prefixo","Orç/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Grupo","Enviar até","Retornar até",
        "Motivo","Condição","Qtdade"
    ]
    mapa_renome = {
        "Or?/OS": "Orç/OS", "Orc/OS": "Orç/OS",
        "Enviar at?": "Enviar até", "Retornar at?": "Retornar até",
        "Condi??o": "Condição", "Condicao": "Condição",
    }
    df = df.rename(columns=mapa_renome)

    # aproxima por nomes normalizados
    norm_cols = {c: _norm(c) for c in df.columns}
    alvo_norm = {a: _norm(a) for a in colunas_importantes}
    ren_extra = {}
    for col_atual, n_atual in norm_cols.items():
        for alvo, n_alvo in alvo_norm.items():
            if n_atual == n_alvo and col_atual != alvo:
                ren_extra[col_atual] = alvo
    if ren_extra:
        df = df.rename(columns=ren_extra)

    # manter apenas o que existe
    keep = [c for c in colunas_importantes if c in df.columns]
    df = df[keep].copy()

    # datas
    for col in ["Enviar até", "Retornar até"]:
        if col in df.columns:
            df[col] = parse_mixed_dates(df[col])

    # textos, qtd
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()
    if "Qtdade" in df.columns:
        df["Qtdade"] = pd.to_numeric(df["Qtdade"], errors="coerce").fillna(0).astype(int)

    # status limpo
    if "Status" in df.columns:
        df["Status"] = df["Status"].apply(limpar_status)

    # derivadas de prazo
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

    # correções pontuais de valores (ex.: 'pe?cas' -> 'Peças')
    df = normalizar_valores(df)
    return df

# ======================== RENDER DE CARDS ========================
def card_badge(texto: str, tone: str = "gray") -> str:
    tone_cls = {"gray":"badge-gray", "blue":"badge-blue", "amber":"badge-amber", "red":"badge-red", "green":"badge-green"}.get(tone,"badge-gray")
    return f'<span class="badge {tone_cls}">{texto}</span>'

def render_cards(dfv: pd.DataFrame):
    """Renderiza itens em cartões; com fallback pra evitar tela branca."""
    if dfv.empty:
        st.info("Nenhum item encontrado com os filtros atuais.")
        return

    try:
        cols = st.columns(3)  # grade de 3 colunas
        i = 0
        for _, row in dfv.iterrows():
            # estilo do card pelo prazo
            card_cls = "card"
            if row.get("Em atraso", False):
                card_cls = "card card-danger"
            elif row.get("Vence em 7 dias", False):
                card_cls = "card card-warn"

            # campos principais
            titulo = str(row.get("Prefixo", "")) or "—"
            sub = str(row.get("Item", "")) or str(row.get("Orç/OS","")) or "—"
            status_txt = str(row.get("Status","—"))
            sit_txt = str(row.get("Sit","")).strip()
            grupo_txt = str(row.get("Grupo","")).strip()
            qtd_val = row.get("Qtdade", "")
            qtd_txt = "" if pd.isna(qtd_val) else str(int(qtd_val)) if str(qtd_val).isdigit() else str(qtd_val)

            dt_ret = row.get("Retornar até", pd.NaT)
            dias = row.get("Dias para devolver", None)

            # badges
            b_status = card_badge(status_txt, "blue" if "P.O" in status_txt else ("red" if status_txt.lower().startswith("n") else "gray"))
            b_sit = card_badge(f"Sit: {sit_txt}") if sit_txt else ""
            b_grupo = card_badge(f"Grupo: {grupo_txt}") if grupo_txt else ""
            b_qtd = card_badge(f"Qtd: {qtd_txt}", "green") if qtd_txt not in ["", "0", "nan"] else ""
            if pd.notna(dt_ret):
                when = dt_ret.strftime("%d/%m/%Y")
                tone = "amber" if (isinstance(dias, (int, float, np.integer, np.floating)) and 0 <= dias <= 7) else ("red" if isinstance(dias, (int, float, np.integer, np.floating)) and dias < 0 else "gray")
                prazo_badge = card_badge(f"Devolver: {when}", tone)
            else:
                prazo_badge = card_badge("Sem data", "gray")

            # linha de contexto de prazo
            prazo_txt = ""
            if isinstance(dias, (int, float, np.integer, np.floating)) and not pd.isna(dias):
                d = int(dias)
                if d < 0:
                    prazo_txt = f"<span class='muted'>Atrasado há {abs(d)} dia(s)</span>"
                elif d == 0:
                    prazo_txt = "<span class='muted'>Vence hoje</span>"
                else:
                    prazo_txt = f"<span class='muted'>Faltam {d} dia(s)</span>"

            with cols[i % 3]:
                st.markdown(
                    f"""
                    <div class="{card_cls}">
                      <div class="card-header">
                        <div class="card-title">{titulo}</div>
                        <div class="card-sub">{sub}</div>
                      </div>
                      <div class="card-row">
                        {b_status}{b_sit}{b_grupo}{b_qtd}{prazo_badge}
                      </div>
                      <div class="card-row">{prazo_txt}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            i += 1
    except Exception as e:
        # Fallback duro: evita "tela branca" se qualquer item der erro
        st.error(f"Falha ao renderizar os cartões ({type(e).__name__}). Mostrando visão alternativa simples.")
        # mostra apenas colunas seguras como texto
        for _, row in dfv.iterrows():
            st.write(
                {
                    "Prefixo": row.get("Prefixo", ""),
                    "Item": row.get("Item", ""),
                    "Status": row.get("Status", ""),
                    "Sit": row.get("Sit", ""),
                    "Grupo": row.get("Grupo", ""),
                    "Retornar até": row.get("Retornar até", ""),
                    "Dias p/ devolver": row.get("Dias para devolver", ""),
                }
            )

# ======================== SIDEBAR (FILTROS) ========================
st.sidebar.title("📌 Filtros")

with st.sidebar.expander("Fonte de dados", expanded=True):
    up = st.file_uploader("Enviar arquivo (.xlsx/.xls/.xlsb)", type=["xlsx","xls","xlsb"])
    if up is not None:
        path = BytesIO(up.read())
    else:
        path = st.text_input("Ou caminho local do Excel", value="reparo_atual.xlsx")

df = carregar_dados(path)

st.sidebar.markdown("### Vistas rápidas")
vista = st.sidebar.radio(
    label="Seleção",
    options=["Todos os itens", "Atrasados", "Próx. 7 dias", "Sem data"],
    index=0,
)

f_status  = st.sidebar.selectbox("Status", ["(Todos)"] + sorted(df["Status"].dropna().astype(str).unique()) if "Status" in df else ["(Todos)"])
f_sit     = st.sidebar.selectbox("Situação (Sit)", ["(Todos)"] + sorted(df["Sit"].dropna().astype(str).unique()) if "Sit" in df else ["(Todos)"])
f_grupo   = st.sidebar.selectbox("Grupo", ["(Todos)"] + sorted(df["Grupo"].dropna().astype(str).unique()) if "Grupo" in df else ["(Todos)"])
f_prefixo = st.sidebar.text_input("Prefixo (contém)")
busca     = st.sidebar.text_input("Busca livre (qualquer coluna)")

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

# Ordenação (para cards)
ordem = st.sidebar.selectbox(
    "Ordenar por",
    [c for c in ["Em atraso","Vence em 7 dias","Dias para devolver","Retornar até","Prefixo","Status","Sit","Grupo","Item","Qtdade"] if c in df.columns]
)
ordem_cresc = st.sidebar.toggle("Ordem crescente", value=False if ordem in ["Em atraso","Vence em 7 dias"] else True)

# ======================== FILTRAGEM ========================
df_f = df.copy()

# vistas rápidas
if vista == "Atrasados" and "Em atraso" in df_f:
    df_f = df_f[df_f["Em atraso"]]
elif vista == "Próx. 7 dias" and "Vence em 7 dias" in df_f:
    df_f = df_f[df_f["Vence em 7 dias"]]
elif vista == "Sem data" and "Sem data" in df_f:
    df_f = df_f[df_f["Sem data"]]
# "Todos os itens": sem restrição por data

# filtros
if f_status != "(Todos)" and "Status" in df_f: df_f = df_f[df_f["Status"].astype(str) == f_status]
if f_sit    != "(Todos)" and "Sit" in df_f:    df_f = df_f[df_f["Sit"].astype(str) == f_sit]
if f_grupo  != "(Todos)" and "Grupo" in df_f:  df_f = df_f[df_f["Grupo"].astype(str) == f_grupo]
if f_prefixo and "Prefixo" in df_f:            df_f = df_f[df_f["Prefixo"].astype(str).str.contains(f_prefixo, case=False, na=False)]

# busca livre
if busca:
    txt = busca.strip().lower()
    mask = pd.Series(False, index=df_f.index)
    for col in df_f.columns:
        mask |= df_f[col].astype(str).str.lower().str.contains(txt, na=False)
    df_f = df_f[mask]

# filtro por datas (opcional)
if habilitar_filtro_datas and date_range and "Retornar até" in df_f and len(date_range) == 2:
    ini, fim = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)
    mask_data = (df_f["Retornar até"] >= ini) & (df_f["Retornar até"] < fim)
    if inclui_sem_data:
        mask_data |= df_f["Retornar até"].isna()
    df_f = df_f[mask_data]
elif not inclui_sem_data and "Retornar até" in df_f:
    df_f = df_f[~df_f["Retornar até"].isna()]

# ordenação
if ordem in df_f.columns:
    secund = "Retornar até" if ("Retornar até" in df_f.columns and ordem != "Retornar até") else None
    if secund:
        df_f = df_f.sort_values(by=[ordem, secund], ascending=[ordem_cresc, True])
    else:
        df_f = df_f.sort_values(by=[ordem], ascending=[ordem_cresc])

# ======================== HEADER & KPIs ========================
st.title("⚒️ Controle de Reparos")

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

st.markdown(
    f"""
    <div class="context">
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
tab1, tab2 = st.tabs(["📋 Itens (cards)", "📊 Agrupamentos"])

with tab1:
    render_cards(df_f[[c for c in ["Prefixo","Item","Orç/OS","Status","Sit","Grupo","Qtdade","Retornar até","Dias para devolver","Em atraso","Vence em 7 dias","Sem data"] if c in df_f.columns]])

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
    if "Sit" in df_f.columns and not df_f.empty:
        st.subheader("Distribuição por Sit")
        st.bar_chart(df_f["Sit"].value_counts().sort_values(ascending=False))

# ======================== RODAPÉ ========================
st.markdown("---")
st.caption("Dica: Cards priorizam leitura rápida; use as Vistas rápidas para alternar entre atrasados, próximos 7 dias e sem data.")


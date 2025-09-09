# ======================== IMPORTS ========================
import re
import unicodedata
from datetime import datetime
from io import BytesIO

import numpy as np
import pandas as pd
import streamlit as st

# ======================== CONFIG & TEMA ========================
st.set_page_config(page_title="Controle de Reparos", page_icon="⚒️", layout="wide", initial_sidebar_state="expanded")

BASE_CSS = """
<style>
div[data-testid="stStatusWidget"], div[data-testid="stDecoration"] { visibility: hidden; height:0; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: .6rem; }
:root{
  --app-bg:#fff; --text:#111827; --muted:#6b7280; --card-bg:#fff; --card-fg:#111827; --border:#e5e7eb;
  --badge-fg:#111827; --badge-gray-bg:#f3f4f6; --badge-gray-bd:#e5e7eb; --badge-blue-bg:#e8f1ff; --badge-blue-bd:#c9ddff;
  --badge-amber-bg:#fff4d6;--badge-amber-bd:#ffe4a6; --badge-red-bg:#ffe6e3;--badge-red-bd:#ffcdc6;
}
@media (prefers-color-scheme: dark){
  :root{
    --app-bg:#000; --text:#f8fafc; --muted:#cbd5e1; --card-bg:#0b0b0b; --card-fg:#f8fafc; --border:#232323;
    --badge-fg:#f8fafc; --badge-gray-bg:#1f2937; --badge-gray-bd:#374151; --badge-blue-bg:#0b254a; --badge-blue-bd:#1e3a8a;
    --badge-amber-bg:#3a2a06;--badge-amber-bd:#a16207; --badge-red-bg:#3b0f0f; --badge-red-bd:#b91c1c;
  }
  html, body, .stApp, [data-testid="stAppViewContainer"], .block-container{
    background: var(--app-bg) !important; color: var(--text) !important;
  }
}
.badge{ display:inline-block; padding:.28rem .6rem; border-radius:999px; font-size:.9rem; font-weight:600; margin-right:.35rem; color: var(--badge-fg) !important; }
.badge-gray { background:var(--badge-gray-bg); border:1px solid var(--badge-gray-bd); }
.badge-blue { background:var(--badge-blue-bg); border:1px solid var(--badge-blue-bd); }
.badge-amber{ background:var(--badge-amber-bg);border:1px solid var(--badge-amber-bd); }
.badge-red  { background:var(--badge-red-bg);  border:1px solid var(--badge-red-bd); }

.grid-cards{ display:grid; grid-template-columns: repeat(auto-fill, minmax(var(--min-card, 240px), 1fr)); gap: 10px; }
.card{
  border:1px solid var(--border); border-radius:14px; padding:12px; background:var(--card-bg);
  box-shadow:0 1px 2px rgba(0,0,0,.08); color: var(--card-fg);
  display:flex; flex-direction:column; gap:6px; min-height:80px;
}
.card-danger{ border-color: var(--badge-red-bd); }
.card-warn{ border-color: var(--badge-amber-bd); }
.card-title{ font-weight:800; font-size:1.05rem; }
.card-sub{ color:var(--muted); font-size:.95rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.row{ display:flex; flex-wrap:wrap; gap:.3rem .45rem; align-items:center; }
.small-muted{ font-size:.9rem; opacity:.85; }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)

# ======================== HELPERS ========================
RE_OS = re.compile(r"^\s*(\d{4})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{3,5})\s*$")
RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_STATUS_PO = re.compile(r"\b(?:p\s*\.?\s*o|po)\b", flags=re.I)

def _norm_str(s: str) -> str:
    """Lower + strip accents + single spaces."""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _choose_engine(path: str | BytesIO | None) -> str | None:
    if isinstance(path, str):
        low = path.lower()
        if low.endswith(".xlsb"): return "pyxlsb"
        if low.endswith(".xlsx"): return "openpyxl"
        if low.endswith(".xls"):  return "xlrd"
    return None

def parse_mixed_dates(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    iso_mask = s.str.match(RE_ISO)
    out = pd.to_datetime(pd.Series(pd.NaT, index=s.index), errors="coerce")
    if iso_mask.any():
        out.loc[iso_mask] = pd.to_datetime(s.loc[iso_mask], format="%Y-%m-%d", errors="coerce")
    if (~iso_mask).any():
        out.loc[~iso_mask] = pd.to_datetime(s.loc[~iso_mask], dayfirst=True, errors="coerce")
    return out

def limpar_status_vec(s: pd.Series) -> pd.Series:
    """Vectorized status -> {'P.O','P.O Fechada','Não comprado', original}."""
    raw = s.fillna("").astype(str)
    nrm = raw.map(_norm_str)
    cond_nao = nrm.str.contains("nao comprad")
    cond_po  = nrm.str.contains(RE_STATUS_PO)
    cond_clo = nrm.str.contains("fechad")
    out = raw.copy()
    out = np.select(
        [cond_nao, cond_po & cond_clo, cond_po],
        ["Não comprado", "P.O Fechada", "P.O"],
        default=raw,
    )
    return pd.Series(out, index=s.index)

def normalizar_os_vec(s: pd.Series) -> pd.Series:
    """Vectorized: 'YYYY/MM/NNNN' or NaN."""
    t = s.astype(str).str.extract(RE_OS)
    if t.empty:
        return pd.Series(pd.NA, index=s.index, dtype="object")
    ano = t[0]
    mes = pd.to_numeric(t[1], errors="coerce")
    seq = pd.to_numeric(t[2], errors="coerce")
    ok = mes.between(1,12) & seq.notna() & ano.notna()
    res = pd.Series(pd.NA, index=s.index, dtype="object")
    res.loc[ok] = (
        ano.loc[ok].astype(int).astype(str).str.zfill(4) + "/" +
        mes.loc[ok].astype(int).astype(str).str.zfill(2) + "/" +
        seq.loc[ok].astype(int).astype(str).str.zfill(4)
    )
    return res

def build_search_index(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Accent-insensitive, lowercased index (cached once)."""
    s = pd.Series([""] * len(df), index=df.index, dtype="object")
    for c in cols:
        if c in df:
            s = s + " " + df[c].fillna("").astype(str)
    return s.map(_norm_str)

# ======================== LOAD (+ CACHE) ========================
@st.cache_data(show_spinner=False)
def carregar_dados(path: str | BytesIO) -> pd.DataFrame:
    engine = _choose_engine(path)
    try:
        df = pd.read_excel(path, sheet_name="Worksheet", engine=engine)
    except Exception:
        xls = pd.ExcelFile(path, engine=engine)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

    mapa_renome = {
        "Or?/OS":"Orç/OS","Orc/OS":"Orç/OS","OS":"Orç/OS","O.S":"Orç/OS",
        "Enviar at?":"Enviar até","Retornar at?":"Retornar até",
        "Condi??o":"Condição","Condicao":"Condição",
        "Situacao":"Sit","Situação":"Sit",
    }
    df = df.rename(columns=mapa_renome)

    cols_keep = [
        "Status","Sit","Prefixo","Orç/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Enviar até","Retornar até","Motivo","Condição","Qtdade"
    ]
    # aproximar por nomes normalizados
    norm_cols = {c: _norm_str(c) for c in df.columns}
    alvo_norm = {a: _norm_str(a) for a in cols_keep}
    ren_extra = {c:a for c,nc in norm_cols.items() for a,na in alvo_norm.items() if nc==na and c!=a}
    if ren_extra: df = df.rename(columns=ren_extra)

    keep = [c for c in cols_keep if c in df.columns]
    df = df[keep].copy()

    # datas (fast path)
    for c in ("Enviar até","Retornar até"):
        if c in df: df[c] = parse_mixed_dates(df[c])

    # tipos
    if "Qtdade" in df: df["Qtdade"] = pd.to_numeric(df["Qtdade"], errors="coerce").fillna(0).astype(int)

    # status (vectorized)
    if "Status" in df: df["Status"] = limpar_status_vec(df["Status"])

    # prazos
    hoje = pd.Timestamp(datetime.now().date())
    if "Retornar até" in df:
        dias = (df["Retornar até"] - hoje).dt.days
        df["Dias para devolver"] = dias
        df["Em atraso"] = (dias < 0)
        df["Vence em 7 dias"] = (dias.between(0,7))
        df["Sem data"] = df["Retornar até"].isna()
    else:
        df["Dias para devolver"] = pd.NA
        df["Em atraso"] = False
        df["Vence em 7 dias"] = False
        df["Sem data"] = True

    # OS normalizada (vectorized) + filtro
    if "Orç/OS" in df:
        osn = normalizar_os_vec(df["Orç/OS"])
        df = df[osn.notna()].copy()
        df["Orç/OS"] = osn.loc[df.index]

    # índice de busca (cacheado no DF)
    df["__search"] = build_search_index(df, ["Item","Insumo","Sit","Status","Prefixo","Orç/OS"])

    return df

# ======================== RENDER (BATCH HTML + PAGINAÇÃO) ========================
def badge(texto: str, tone: str = "gray") -> str:
    cls = {"gray":"badge-gray","blue":"badge-blue","amber":"badge-amber","red":"badge-red"}.get(tone,"badge-gray")
    return f'<span class="badge {cls}">{texto}</span>'

def render_cards_html(dfv: pd.DataFrame, min_card_px: int = 240) -> None:
    if dfv.empty:
        st.info("Nenhum item encontrado.")
        return
    parts = [f'<div class="grid-cards" style="--min-card:{int(min_card_px)}px;">']
    # itertuples is much faster than iterrows
    cols = dfv.columns
    idx_item = cols.get_loc("Item")
    idx_insumo = cols.get_loc("Insumo") if "Insumo" in cols else None
    idx_sit = cols.get_loc("Sit") if "Sit" in cols else None
    idx_status = cols.get_loc("Status") if "Status" in cols else None
    idx_prefixo = cols.get_loc("Prefixo") if "Prefixo" in cols else None
    idx_ret = cols.get_loc("Retornar até") if "Retornar até" in cols else None
    idx_dias = cols.get_loc("Dias para devolver") if "Dias para devolver" in cols else None
    idx_atraso = cols.get_loc("Em atraso") if "Em atraso" in cols else None
    idx_v7 = cols.get_loc("Vence em 7 dias") if "Vence em 7 dias" in cols else None

    for row in dfv.itertuples(index=False, name=None):
        cls = "card"
        if idx_atraso is not None and bool(row[idx_atraso]): cls += " card-danger"
        elif idx_v7 is not None and bool(row[idx_v7]): cls += " card-warn"

        item = str(row[idx_item]) if row[idx_item] not in (None, np.nan) else "—"
        insumo = str(row[idx_insumo]) if (idx_insumo is not None and row[idx_insumo] not in (None, np.nan)) else "—"
        sit = str(row[idx_sit]).strip() if idx_sit is not None else ""
        status = str(row[idx_status]).strip() if idx_status is not None else ""
        prefixo = str(row[idx_prefixo]).strip() if idx_prefixo is not None else ""

        chips = []
        if sit:     chips.append(badge(f"Situação: {sit}"))
        if status:  chips.append(badge(f"Status: {status}", "blue" if "P.O" in status else ("red" if status.lower().startswith("n") else "gray")))
        if prefixo: chips.append(badge(f"Prefixo: {prefixo}"))

        prazo_chip = badge("Sem data","gray")
        ctx = ""
        if idx_ret is not None and pd.notna(row[idx_ret]):
            when = pd.to_datetime(row[idx_ret]).strftime("%d/%m/%Y")
            d = row[idx_dias] if idx_dias is not None else None
            tone = "gray"
            if isinstance(d,(int,float,np.integer,np.floating)):
                if d < 0: tone = "red"
                elif 0 <= d <= 7: tone = "amber"
            prazo_chip = badge(f"Retornar até: {when}", tone)
            if isinstance(d,(int,float,np.integer,np.floating)):
                d = int(d)
                if d < 0: ctx = f"<span class='small-muted'>Atrasado há {abs(d)} dia(s)</span>"
                elif d == 0: ctx = "<span class='small-muted'>Vence hoje</span>"
                else: ctx = f"<span class='small-muted'>Faltam {d} dia(s)</span>"

        parts.append(f"""
        <div class="{cls}">
          <div class="card-title">{item}</div>
          <div class="card-sub">{insumo}</div>
          <div class="row">{''.join(chips)} {prazo_chip}</div>
          <div class="row">{ctx}</div>
        </div>
        """)
    parts.append("</div>")
    st.markdown("\n".join(parts), unsafe_allow_html=True)

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
vista = st.sidebar.radio("Seleção", ["Todos os itens", "Atrasados", "Próx. 7 dias", "Sem data"], index=0)

f_status  = st.sidebar.selectbox("Status", ["(Todos)"] + (sorted(df["Status"].dropna().astype(str).unique()) if "Status" in df else []))
f_sit     = st.sidebar.selectbox("Situação (Sit)", ["(Todos)"] + (sorted(df["Sit"].dropna().astype(str).unique()) if "Sit" in df else []))
f_prefixo = st.sidebar.text_input("Prefixo (contém)")
busca     = st.sidebar.text_input("Busca livre (qualquer coluna)")

st.sidebar.markdown("---")
inclui_sem_data = st.sidebar.checkbox("Incluir itens sem data", value=True)
habilitar_filtro_datas = st.sidebar.checkbox("Filtrar por 'Retornar até'", value=False)
if habilitar_filtro_datas and "Retornar até" in df.columns:
    min_d, max_d = df["Retornar até"].min(), df["Retornar até"].max()
    date_range = st.sidebar.date_input("Janela de 'Retornar até'", value=(min_d.date(), max_d.date())) if pd.notna(min_d) and pd.notna(max_d) else None
else:
    date_range = None

st.sidebar.markdown("---")
# PAGINAÇÃO (grande impacto de performance em listas grandes)
page_size = st.sidebar.slider("Itens por página", 24, 240, 60, step=12)
page = st.sidebar.number_input("Página", min_value=1, value=1, step=1)

ordem = st.sidebar.selectbox("Ordenar por",
    [c for c in ["Em atraso","Vence em 7 dias","Dias para devolver","Retornar até","Item","Insumo","Prefixo","Status","Sit","Qtdade","Orç/OS"] if c in df.columns])
ordem_cresc = st.sidebar.toggle("Ordem crescente", value=False if ordem in ["Em atraso","Vence em 7 dias"] else True)

# ======================== FILTRAGEM (VETORIZADA) ========================
df_f = df.copy()

if vista == "Atrasados" and "Em atraso" in df_f: df_f = df_f[df_f["Em atraso"]]
elif vista == "Próx. 7 dias" and "Vence em 7 dias" in df_f: df_f = df_f[df_f["Vence em 7 dias"]]
elif vista == "Sem data" and "Sem data" in df_f: df_f = df_f[df_f["Sem data"]]

if f_status != "(Todos)" and "Status" in df_f: df_f = df_f[df_f["Status"].astype(str) == f_status]
if f_sit    != "(Todos)" and "Sit" in df_f:    df_f = df_f[df_f["Sit"].astype(str) == f_sit]
if f_prefixo and "Prefixo" in df_f:            df_f = df_f[df_f["Prefixo"].astype(str).str.contains(f_prefixo, case=False, na=False)]

if busca:
    q = _norm_str(busca)
    df_f = df_f[df_f["__search"].str.contains(q, regex=False, na=False)]

if habilitar_filtro_datas and date_range and "Retornar até" in df_f and len(date_range) == 2:
    ini, fim = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)
    mask = (df_f["Retornar até"] >= ini) & (df_f["Retornar até"] < fim)
    if inclui_sem_data: mask |= df_f["Retornar até"].isna()
    df_f = df_f[mask]
elif not inclui_sem_data and "Retornar até" in df_f:
    df_f = df_f[~df_f["Retornar até"].isna()]

if ordem in df_f.columns:
    sec = "Retornar até" if ("Retornar até" in df_f.columns and ordem != "Retornar até") else None
    df_f = df_f.sort_values(by=[ordem, sec] if sec else [ordem], ascending=[ordem_cresc, True] if sec else [ordem_cresc])

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
    <div style="margin:.5rem 0 .75rem 0;">
      <span class="badge badge-blue">Ordenado por: {ordem} {'↑' if ordem_cresc else '↓'}</span>
      <span class="badge badge-gray">Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</span>
    </div>
    """, unsafe_allow_html=True,
)
st.markdown("---")

# ======================== ITENS (CARDS COM PAGINAÇÃO) ========================
subset = [c for c in ["Item","Insumo","Sit","Status","Prefixo","Retornar até","Dias para devolver","Em atraso","Vence em 7 dias"] if c in df_f.columns]
df_view = df_f[subset]

# paginate
start = (page - 1) * page_size
end = start + page_size
total_pages = max(1, int(np.ceil(len(df_view) / page_size)))
if page > total_pages:
    st.warning(f"Página {page} maior que o total ({total_pages}). Ajustado para {total_pages}.")
    page = total_pages
    start = (page - 1) * page_size
    end = start + page_size

st.caption(f"Mostrando {min(len(df_view), page_size)} de {len(df_view)} itens  ·  página {page}/{total_pages}")
render_cards_html(df_view.iloc[start:end].copy(), min_card_px=240)

# ======================== AGRUPAMENTOS (leves) ========================
st.markdown("---")
ca, cb = st.columns(2)
with ca:
    if "Status" in df_f and not df_f.empty:
        st.subheader("Distribuição por Status")
        st.bar_chart(df_f["Status"].value_counts().sort_values(ascending=False))
with cb:
    if "Sit" in df_f and not df_f.empty:
        st.subheader("Distribuição por Sit")
        st.bar_chart(df_f["Sit"].value_counts().sort_values(ascending=False))

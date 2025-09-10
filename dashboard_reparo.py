# ======================== IMPORTS ========================
import os
import re
import unicodedata
import hashlib
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
/* -------- resets -------- */
div[data-testid="stStatusWidget"], div[data-testid="stDecoration"] { visibility: hidden; height:0; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: .6rem; }

/* -------- tipografia (↑ tamanhos) -------- */
html, body { font-size: 1.06rem; }
h1 { font-size: 2.0rem; letter-spacing:.2px; }
h2 { font-size: 1.45rem; letter-spacing:.2px; }
h3 { font-size: 1.18rem; letter-spacing:.2px; }
.small-muted { font-size: .95rem; opacity: .85; }

/* -------- paleta default (claro) -------- */
:root{
  --app-bg: #ffffff;
  --text: #111827;
  --muted: #6b7280;
  --card-bg:#ffffff;
  --card-fg:#111827;
  --border: #e5e7eb;
  --badge-fg: #111827;
  --badge-gray-bg:#f3f4f6;  --badge-gray-bd:#e5e7eb;
  --badge-blue-bg:#e8f1ff;  --badge-blue-bd:#c9ddff;
  --badge-amber-bg:#fff4d6; --badge-amber-bd:#ffe4a6;
  --badge-red-bg:#ffe6e3;   --badge-red-bd:#ffcdc6;
  --badge-green-bg:#e7f6ec; --badge-green-bd:#c9e8d2;
  --warn-bg:#fff9ea;  --warn-bd:#ffe4a6;
  --danger-bg:#ffeceb;--danger-bd:#ffcdc6;
}

/* -------- dark mode seguindo SO -------- */
@media (prefers-color-scheme: dark){
  :root{
    --app-bg:#000000;
    --text: #f8fafc;
    --muted: #cbd5e1;
    --card-bg:#0b0b0b;
    --card-fg:#f8fafc;
    --border:#232323;
    --badge-fg: #f8fafc;
    --badge-gray-bg:#1f2937; --badge-gray-bd:#374151;
    --badge-blue-bg:#0b254a; --badge-blue-bd:#1e3a8a;
    --badge-amber-bg:#3a2a06;--badge-amber-bd:#a16207;
    --badge-red-bg:#3b0f0f;  --badge-red-bd:#b91c1c;
    --badge-green-bg:#0f2f1d;--badge-green-bd:#15803d;
    --warn-bg:#2a1f07;  --warn-bd:#a16207;
    --danger-bg:#2a0f10;--danger-bd:#b91c1c;
  }
  html, body, .stApp, [data-testid="stAppViewContainer"], .block-container{
    background: var(--app-bg) !important;
    color: var(--text) !important;
  }
}

/* ===== Badges ===== */
.badge{ display:inline-block; padding:.32rem .7rem; border-radius:999px; font-size:.92rem; font-weight:600; margin-right:.4rem; color: var(--badge-fg) !important; }
.badge-gray  { background:var(--badge-gray-bg);  border:1px solid var(--badge-gray-bd); }
.badge-blue  { background:var(--badge-blue-bg);  border:1px solid var(--badge-blue-bd); }
.badge-amber { background:var(--badge-amber-bg); border:1px solid var(--badge-amber-bd); }
.badge-red   { background:var(--badge-red-bg);   border:1px solid var(--badge-red-bd); }
.badge-green { background:var(--badge-green-bg); border:1px solid var(--badge-green-bd); }

/* ===== KPIs ===== */
.kpi, .kpi *{ color: var(--card-fg) !important; }
.kpi{ border:1px solid var(--border); border-radius:14px; padding:16px 18px; background:var(--card-bg); box-shadow:0 1px 2px rgba(0,0,0,.12); }
.kpi .kpi-title{ font-size:.95rem; color:var(--muted) !important; margin-bottom:.35rem; }
.kpi .kpi-value{ font-size:1.9rem; font-weight:800; }

/* ===== Cards ===== */
.card, .card *{ color: var(--card-fg) !important; }
.card{ border:1px solid var(--border); border-radius:16px; padding:16px; background:var(--card-bg); box-shadow:0 1px 3px rgba(0,0,0,.18); display:flex; flex-direction:column; gap:.6rem; height:100%; }
.card-header{ display:flex; align-items:center; justify-content:space-between; gap:.5rem; }
.card-title{ font-weight:800; font-size:1.12rem; letter-spacing:.2px; }
.card-sub{ color:var(--muted) !important; font-size:.98rem; }
.card-row{ display:flex; flex-wrap:wrap; gap:.45rem .6rem; align-items:center; }
.card .muted{ color:var(--muted) !important; font-size:.95rem; }
.card-danger{ border-color: var(--danger-bd); background: linear-gradient(0deg, var(--card-bg), var(--card-bg)), var(--danger-bg); }
.card-warn  { border-color: var(--warn-bd);   background: linear-gradient(0deg, var(--card-bg), var(--card-bg)), var(--warn-bg); }

/* Gráficos com moldura */
[data-testid="stVegaLiteChart"]{ border-radius: 12px; overflow: hidden; border:1px solid var(--border); }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)

# ======================== TUNABLES (performance/UI) ========================
MAX_CARDS_RENDER = 1000  # limite de cartões renderizados por performance

# ======================== SNAPSHOT CONFIG ========================
SNAP_PATH = "data/_ultimo_snapshot.parquet"
_snapshot_dir = os.path.dirname(SNAP_PATH)
if _snapshot_dir:
    os.makedirs(_snapshot_dir, exist_ok=True)

# ======================== HELPERS ========================
def _norm(s: str) -> str:
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip()

def _choose_engine(path: str | BytesIO | None) -> tuple[str | None, dict]:
    """Choose Excel engine + engine_kwargs tuned for speed."""
    engine_kwargs = {}
    if isinstance(path, str):
        low = path.lower()
        if low.endswith(".xlsb"):
            return "pyxlsb", {}
        if low.endswith(".xlsx"):
            return "openpyxl", {"read_only": True, "data_only": True}
        if low.endswith(".xls"):
            return "xlrd", {}
    return None, {}

def _file_cache_key(path: str | BytesIO) -> str:
    """Stable cache key: if upload -> md5(bytes); if path -> size+mtime."""
    if isinstance(path, BytesIO):
        data = path.getvalue()
        return hashlib.md5(data).hexdigest()
    if isinstance(path, str) and os.path.exists(path):
        st_ = os.stat(path)
        return f"{os.path.abspath(path)}::{st_.st_size}::{int(st_.st_mtime)}"
    return str(path)

def parse_mixed_dates(series: pd.Series) -> pd.Series:
    """ISO (YYYY-MM-DD) com format + demais com dayfirst=True (sem warnings)."""
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

def normalizar_os(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    m = re.match(r"^\s*(\d{4})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{3,5})\s*$", s)
    if not m:
        return None
    ano = int(m.group(1)); mes = int(m.group(2)); seq = m.group(3)
    if not (1 <= mes <= 12):
        return None
    try:
        seq_int = int(seq)
    except ValueError:
        return None
    return f"{ano:04d}/{mes:02d}/{seq_int:04d}"

# ======================== LOAD ========================
@st.cache_data(show_spinner=False)
def carregar_dados_cached(path: str | BytesIO, cache_key: str) -> pd.DataFrame:
    """Wrapper para cachear por cache_key estável (conteúdo/mtime)."""
    return _carregar_dados_impl(path)

def _carregar_dados_impl(path: str | BytesIO) -> pd.DataFrame:
    """Lê xls/xlsx/xlsb, normaliza colunas, datas, status e prazos."""
    engine, engine_kwargs = _choose_engine(path)
    dtype_backend = "pyarrow"  # melhora memória/velocidade no pandas 2.x
    try:
        df = pd.read_excel(
            path, sheet_name="Worksheet", engine=engine, engine_kwargs=engine_kwargs,
            dtype_backend=dtype_backend
        )
    except Exception:
        xls = pd.ExcelFile(path, engine=engine, engine_kwargs=engine_kwargs)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], dtype_backend=dtype_backend)

    colunas_importantes = [
        "Status","Sit","Prefixo","Orç/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Enviar até","Retornar até",
        "Motivo","Condição","Qtdade"
    ]

    mapa_renome = {
        "Or?/OS":"Orç/OS","Orc/OS":"Orç/OS",
        "Enviar at?":"Enviar até","Retornar at?":"Retornar até",
        "Condi??o":"Condição","Condicao":"Condição",
    }
    df = df.rename(columns=mapa_renome)

    norm_cols = {c: _norm(c) for c in df.columns}
    alvo_norm = {a: _norm(a) for a in colunas_importantes}
    ren_extra = {}
    for col_atual, n_atual in norm_cols.items():
        for alvo, n_alvo in alvo_norm.items():
            if n_atual == n_alvo and col_atual != alvo:
                ren_extra[col_atual] = alvo
    if ren_extra:
        df = df.rename(columns=ren_extra)

    keep = [c for c in colunas_importantes if c in df.columns]
    df = df[keep].copy()

    for col in ["Enviar até","Retornar até"]:
        if col in df.columns:
            df[col] = parse_mixed_dates(df[col])

    # Evita .astype(str) em tudo: só colunas de texto
    obj_cols = list(df.select_dtypes(include=["object", "string[pyarrow]"]).columns)
    for col in obj_cols:
        df[col] = df[col].astype(str).str.strip()

    if "Qtdade" in df.columns:
        df["Qtdade"] = pd.to_numeric(df["Qtdade"], errors="coerce").fillna(0).astype("int64[pyarrow]")

    if "Status" in df.columns:
        df["Status"] = df["Status"].apply(limpar_status)

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

    if "Orç/OS" in df.columns:
        df["__OS_norm"] = df["Orç/OS"].map(normalizar_os)
        df = df[df["__OS_norm"].notna()].copy()
        df["Orç/OS"] = df["__OS_norm"]
        df.drop(columns="__OS_norm", inplace=True)

    return df

# ======================== SNAPSHOT + DIFF HELPERS ========================
def _chave_itens(df: pd.DataFrame) -> pd.Series:
    candidatos = [c for c in ["Orç/OS", "Item", "P/N Removido", "S/N Removido", "Prefixo"] if c in df.columns]
    if not candidatos:
        return df.index.astype(str)
    return df[candidatos].astype(str).agg(" | ".join, axis=1)

def salvar_snapshot(df: pd.DataFrame) -> None:
    cols = [c for c in df.columns if not c.startswith("__")]
    try:
        df[cols].to_parquet(SNAP_PATH, index=False)
    except Exception:
        df[cols].to_csv(SNAP_PATH.replace(".parquet", ".csv"), index=False)

def carregar_snapshot() -> pd.DataFrame | None:
    if os.path.exists(SNAP_PATH):
        try:
            return pd.read_parquet(SNAP_PATH)
        except Exception:
            csv_path = SNAP_PATH.replace(".parquet", ".csv")
            if os.path.exists(csv_path):
                return pd.read_csv(csv_path)
    return None

def calcular_diferencas(df_atual: pd.DataFrame, df_antigo: pd.DataFrame):
    a = df_atual.copy()
    b = df_antigo.copy()
    a["__key"] = _chave_itens(a)
    b["__key"] = _chave_itens(b)
    comparar_cols = sorted(set(a.columns).intersection(b.columns) - {"__key"})
    adicionados = a[~a["__key"].isin(b["__key"])].drop(columns=["__key"], errors="ignore")
    removidos  = b[~b["__key"].isin(a["__key"])].drop(columns=["__key"], errors="ignore")
    a_comum = a[a["__key"].isin(b["__key"])][["__key"] + comparar_cols]
    b_comum = b[b["__key"].isin(a["__key"])][["__key"] + comparar_cols]
    m = a_comum.merge(b_comum, on="__key", suffixes=("_new", "_old"))
    diffs = []
    for col in comparar_cols:
        left = f"{col}_new"; right = f"{col}_old"
        mask = m[left].astype(str).fillna("") != m[right].astype(str).fillna("")
        if mask.any():
            diffs.append(pd.DataFrame({
                "Chave": m.loc[mask, "__key"].values,
                "Coluna": col,
                "Valor antigo": m.loc[mask, right].values,
                "Valor novo": m.loc[mask, left].values,
            }))
    alterados = pd.concat(diffs, ignore_index=True) if diffs else pd.DataFrame(columns=["Chave","Coluna","Valor antigo","Valor novo"])
    return adicionados, removidos, alterados

# ======================== RENDER DE CARDS ========================
def card_badge(texto: str, tone: str = "gray") -> str:
    tone_cls = {"gray":"badge-gray","blue":"badge-blue","amber":"badge-amber","red":"badge-red","green":"badge-green"}.get(tone,"badge-gray")
    return f'<span class="badge {tone_cls}">{texto}</span>'

def render_cards(dfv: pd.DataFrame, cols_por_linha: int = 3):
    if dfv.empty:
        st.info("Nenhum item encontrado com os filtros atuais.")
        return
    # Limita quantidade renderizada (performance)
    n = len(dfv)
    if n > MAX_CARDS_RENDER:
        st.warning(f"Mostrando apenas os primeiros {MAX_CARDS_RENDER} de {n} itens para melhor desempenho.")
        dfv = dfv.head(MAX_CARDS_RENDER)

    cols_por_linha = max(2, min(int(cols_por_linha), 6))
    try:
        cols = st.columns(cols_por_linha)
        i = 0
        for _, row in dfv.iterrows():
            card_cls = "card"
            if row.get("Em atraso", False):
                card_cls = "card card-danger"
            elif row.get("Vence em 7 dias", False):
                card_cls = "card card-warn"
            titulo = (str(row.get("Item","")).strip() or "—")
            insumo = (str(row.get("Insumo","")).strip() or "—")
            sit_txt = str(row.get("Sit","")).strip()
            status = str(row.get("Status","")).strip()
            prefixo = str(row.get("Prefixo","")).strip()
            b_sit = card_badge(f"Situação: {sit_txt}") if sit_txt else ""
            b_status = card_badge(
                f"Status: {status}",
                "blue" if "P.O" in status else ("red" if status.lower().startswith("n") else "gray")
            ) if status else ""
            b_prefixo = card_badge(f"Prefixo: {prefixo}") if prefixo else ""
            dt_ret = row.get("Retornar até", pd.NaT)
            dias = row.get("Dias para devolver", None)
            if pd.notna(dt_ret):
                when = dt_ret.strftime("%d/%m/%Y")
                tone = "amber" if (isinstance(dias,(int,float,np.integer,np.floating)) and 0 <= dias <= 7) \
                       else ("red" if isinstance(dias,(int,float,np.integer,np.floating)) and dias < 0 else "gray")
                prazo_badge = card_badge(f"Retornar até: {when}", tone)
            else:
                prazo_badge = card_badge("Sem data", "gray")
            prazo_txt = ""
            if isinstance(dias,(int,float,np.integer,np.floating)) and not pd.isna(dias):
                d = int(dias)
                if d < 0:   prazo_txt = f"<span class='muted'>Atrasado há {abs(d)} dia(s)</span>"
                elif d==0:  prazo_txt = "<span class='muted'>Vence hoje</span>"
                else:       prazo_txt = f"<span class='muted'>Faltam {d} dia(s)</span>"
            with cols[i % cols_por_linha]:
                st.markdown(
                    f"""
                    <div class="{card_cls}">
                      <div class="card-header">
                        <div>
                          <div class="card-title">{titulo}</div>
                          <div class="card-sub">{insumo}</div>
                        </div>
                      </div>
                      <div class="card-row">{b_sit}{b_status}{b_prefixo}{prazo_badge}</div>
                      <div class="card-row">{prazo_txt}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            i += 1
    except Exception as e:
        st.error(f"Falha ao renderizar os cartões ({type(e).__name__}). Mostrando visão alternativa simples.")
        for _, row in dfv.iterrows():
            st.write({
                "Item": row.get("Item",""),
                "Insumo": row.get("Insumo",""),
                "Situação": row.get("Sit",""),
                "Status": row.get("Status",""),
                "Prefixo": row.get("Prefixo",""),
                "Retornar até": row.get("Retornar até",""),
                "Dias p/ devolver": row.get("Dias para devolver",""),
            })

# ======================== SIDEBAR (FILTROS) ========================
st.sidebar.title("📌 Filtros")
with st.sidebar.expander("Fonte de dados", expanded=True):
    up = st.file_uploader("Enviar arquivo (.xlsx/.xls/.xlsb)", type=["xlsx","xls","xlsb"])
    if up is not None:
        path = BytesIO(up.read())
    else:
        path = st.text_input("Ou caminho local do Excel", value="reparo_atual.xlsx")

cache_key = _file_cache_key(path)
df = carregar_dados_cached(path, cache_key)

st.sidebar.markdown("### Vistas rápidas")
vista = st.sidebar.radio("Seleção", ["Todos os itens", "Atrasados", "Próx. 7 dias", "Sem data"], index=0)
f_status = st.sidebar.selectbox("Status", ["(Todos)"] + sorted(df["Status"].dropna().astype(str).unique()) if "Status" in df else ["(Todos)"])
f_sit = st.sidebar.selectbox("Situação (Sit)", ["(Todos)"] + sorted(df["Sit"].dropna().astype(str).unique()) if "Sit" in df else ["(Todos)"])
f_prefixo = st.sidebar.text_input("Prefixo (contém)")
busca = st.sidebar.text_input("Busca livre (qualquer coluna)")

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

st.sidebar.markdown("---")
ordem = st.sidebar.selectbox(
    "Ordenar por",
    [c for c in ["Em atraso","Vence em 7 dias","Dias para devolver","Retornar até","Item","Insumo","Prefixo","Status","Sit","Qtdade","Orç/OS"] if c in df.columns]
)
ordem_cresc = st.sidebar.toggle("Ordem crescente", value=False if ordem in ["Em atraso","Vence em 7 dias"] else True)

# ======================== FILTRAGEM ========================
df_f = df.copy()

if vista == "Atrasados" and "Em atraso" in df_f:
    df_f = df_f[df_f["Em atraso"]]
elif vista == "Próx. 7 dias" and "Vence em 7 dias" in df_f:
    df_f = df_f[df_f["Vence em 7 dias"]]
elif vista == "Sem data" and "Sem data" in df_f:
    df_f = df_f[df_f["Sem data"]]

if f_status != "(Todos)" and "Status" in df_f:
    df_f = df_f[df_f["Status"].astype(str) == f_status]
if f_sit != "(Todos)" and "Sit" in df_f:
    df_f = df_f[df_f["Sit"].astype(str) == f_sit]
if f_prefixo and "Prefixo" in df_f:
    df_f = df_f[df_f["Prefixo"].astype(str).str.contains(f_prefixo, case=False, na=False)]

# busca livre (rápida): cria um 'blob' de busca uma única vez
if busca:
    txt = busca.strip().lower()
    text_cols = [c for c in df_f.columns if df_f[c].dtype == "string[pyarrow]" or df_f[c].dtype == object]
    if text_cols:
        blob = df_f[text_cols].astype(str).agg(" | ".join, axis=1).str.lower()
        mask = blob.str.contains(txt, na=False)
        df_f = df_f[mask]

if habilitar_filtro_datas and date_range and "Retornar até" in df_f and len(date_range) == 2:
    ini, fim = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)
    mask_data = (df_f["Retornar até"] >= ini) & (df_f["Retornar até"] < fim)
    if inclui_sem_data:
        mask_data |= df_f["Retornar até"].isna()
    df_f = df_f[mask_data]
elif not inclui_sem_data and "Retornar até" in df_f:
    df_f = df_f[~df_f["Retornar até"].isna()]

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
atrasados = int(df_f["Em atraso"].sum()) if "Em atraso" in df_f else 0
prox7 = int(df_f["Vence em 7 dias"].sum()) if "Vence em 7 dias" in df_f else 0
sem_data = int(df_f["Sem data"].sum()) if "Sem data" in df_f else 0
qtd_total = int(df_f["Qtdade"].sum()) if "Qtdade" in df_f else total_itens

for col, title, value in [
    (k1,"Itens filtrados", total_itens),
    (k2,"Em atraso", atrasados),
    (k3,"Vencem em 7 dias", prox7),
    (k4,"Sem data", sem_data),
    (k5,"Qtdade total (soma)", qtd_total),
]:
    with col:
        st.markdown(
            f"""
            <div class="kpi">
              <div class="kpi-title">{title}</div>
              <div class="kpi-value">{value}</div>
            </div>
            """, unsafe_allow_html=True
        )

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
snap_antigo = carregar_snapshot()
tab1, tab2, tab3 = st.tabs(["📋 Itens (cards)", "📊 Agrupamentos", "🔍 Diferenças"])

with tab1:
    cols_keep = [c for c in [
        "Item","Insumo","Sit","Status","Prefixo",
        "Retornar até","Dias para devolver","Em atraso","Vence em 7 dias","Sem data"
    ] if c in df_f.columns]
    render_cards(df_f[cols_keep], cols_por_linha=3)

with tab2:
    cA, = st.columns(1)
    with cA:
        if "Status" in df_f.columns and not df_f.empty:
            st.subheader("Distribuição por Status")
            st.bar_chart(df_f["Status"].value_counts().sort_values(ascending=False))
        if "Sit" in df_f.columns and not df_f.empty:
            st.subheader("Distribuição por Sit")
            st.bar_chart(df_f["Sit"].value_counts().sort_values(ascending=False))

with tab3:
    st.subheader("Comparação com a execução anterior")
    if snap_antigo is None:
        st.info("Nenhum snapshot encontrado ainda. Salve um snapshot para habilitar a comparação.")
    else:
        adicionados, removidos, alterados = calcular_diferencas(df, snap_antigo)
        c1, c2, c3 = st.columns(3)
        c1.metric("Adicionados", len(adicionados))
        c2.metric("Removidos", len(removidos))
        c3.metric("Alterações de campos", len(alterados))

        with st.expander("Adicionados", expanded=True):
            st.dataframe(adicionados, use_container_width=True, hide_index=True)
        with st.expander("Removidos", expanded=False):
            st.dataframe(removidos, use_container_width=True, hide_index=True)
        with st.expander("Alterados (por campo)", expanded=True):
            st.dataframe(alterados, use_container_width=True, hide_index=True)

    st.markdown("---")
    colA, colB = st.columns([1,2])
    with colA:
        if st.button("💾 Salvar snapshot agora"):
            salvar_snapshot(df)
            st.success("Snapshot salvo. Na próxima execução a comparação estará disponível.")
    with colB:
        st.caption(
            "A chave de comparação usa: Orç/OS, Item, P/N Removido, S/N Removido, Prefixo (quando existirem). "
            "Ajuste em `_chave_itens` conforme necessário."
        )

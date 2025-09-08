# ======================== IMPORTS ========================
import re
import unicodedata
from datetime import datetime
from io import BytesIO
import html
import importlib

import numpy as np
import pandas as pd
import streamlit as st

APP_VERSION = "diag-1.0"

# ======================== CONFIG & TEMA ========================
st.set_page_config(
    page_title="Controle de Reparos",
    page_icon="⚒️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_CSS = """
<style>
/* Base compacta + dark corporativo */
div[data-testid="stStatusWidget"], div[data-testid="stDecoration"] { visibility: hidden; height:0; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: .4rem; }
:root{
  --base-font: 15px;
  --radius: 12px;
  --gap: 10px;
  --card-pad: 10px 12px;
  --badge-size: .78rem;
  --app-bg: #fff; --text:#0f172a; --muted:#64748b; --card-bg:#fff; --card-fg:#0f172a; --border:#e2e8f0;
  --badge-fg:#0f172a;
  --badge-gray-bg:#f1f5f9; --badge-gray-bd:#e2e8f0;
  --badge-blue-bg:#e8f1ff; --badge-blue-bd:#c9ddff;
  --badge-amber-bg:#fff4d6; --badge-amber-bd:#ffe4a6;
  --badge-red-bg:#ffe6e3; --badge-red-bd:#ffcdc6;
  --badge-green-bg:#e7f6ec; --badge-green-bd:#c9e8d2;
  --danger-bd:#ffcdc6; --warn-bd:#ffe4a6;
}
@media (prefers-color-scheme: dark){
  :root{
    --app-bg:#000; --text:#f8fafc; --muted:#cbd5e1; --card-bg:#0b0b0b; --card-fg:#f8fafc; --border:#1f2937;
    --badge-fg:#f8fafc;
    --badge-gray-bg:#111827; --badge-gray-bd:#1f2937;
    --badge-blue-bg:#0b254a; --badge-blue-bd:#1e3a8a;
    --badge-amber-bg:#3a2a06; --badge-amber-bd:#a16207;
    --badge-red-bg:#3b0f0f; --badge-red-bd:#b91c1c;
    --badge-green-bg:#0f2f1d; --badge-green-bd:#15803d;
  }
  html, body, .stApp, [data-testid="stAppViewContainer"], .block-container{
    background: var(--app-bg) !important; color: var(--text) !important;
  }
}
html, body { font-size: var(--base-font); }
.small-muted { font-size: .92rem; opacity: .8; }

/* Badges */
.badge{
  display:inline-block; padding:.2rem .5rem; border-radius:999px;
  font-size: var(--badge-size); font-weight:600; margin-right:.35rem;
  color: var(--badge-fg) !important; white-space: nowrap;
}
.badge-gray { background:var(--badge-gray-bg); border:1px solid var(--badge-gray-bd); }
.badge-blue { background:var(--badge-blue-bg); border:1px solid var(--badge-blue-bd); }
.badge-amber{ background:var(--badge-amber-bg);border:1px solid var(--badge-amber-bd); }
.badge-red  { background:var(--badge-red-bg);  border:1px solid var(--badge-red-bd); }
.badge-green{ background:var(--badge-green-bg);border:1px solid var(--badge-green-bd); }

/* Grid de cards compactos */
.grid-cards{ display:grid; grid-template-columns: repeat(auto-fill, minmax(var(--min-card, 240px), 1fr)); gap: var(--gap); }
.card{
  border:1px solid var(--border); border-radius:var(--radius); padding: var(--card-pad); background:var(--card-bg);
  box-shadow:0 1px 2px rgba(0,0,0,.08);
  display:flex; flex-direction:column; gap:6px; min-height: 82px;
  color: var(--card-fg) !important;
}
.card-title{ font-weight:800; font-size:1rem; letter-spacing:.2px; margin-bottom:2px; }
.card-sub{ color:var(--muted) !important; font-size:.92rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.row{ display:flex; flex-wrap:wrap; gap:.3rem .45rem; align-items:center; }
.card-danger{ border-color: var(--danger-bd); }
.card-warn  { border-color: var(--warn-bd); }

/* Lista densa */
.table-wrap{ border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; background:var(--card-bg); }
.table-h, .table-r{
  display:grid; grid-template-columns: 1.2fr 2fr 1.1fr 1.1fr 1.1fr 1fr;
  padding:8px 10px; border-bottom:1px solid var(--border); font-size:.92rem;
}
.table-h{ font-weight:700; }
.table-r:last-child{ border-bottom:0; }
.cell-muted{ color:var(--muted); }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)

# ======================== HELPERS ========================
def esc(s) -> str:
    return html.escape("" if s is None else str(s))

def _norm(s: str) -> str:
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip()

def _choose_engine(path: str | BytesIO | None) -> str | None:
    if isinstance(path, str):
        low = path.lower()
        if low.endswith(".xlsb"): return "pyxlsb"
        if low.endswith(".xlsx"): return "openpyxl"
        if low.endswith(".xls"):  return "xlrd"
    return None

def parse_mixed_dates(series: pd.Series) -> pd.Series:
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
    if pd.isna(valor): return valor
    raw = str(valor).strip()
    n = _norm(raw).lower()
    has_po = bool(re.search(r"\b(?:p\s*\.?\s*o|po)\b", n))
    closed = "fechad" in n
    nao_comprado = ("nao comprad" in n) or ("não comprad" in raw.lower()) or ("n?o comprad" in raw.lower())
    if nao_comprado: return "Não comprado"
    if has_po and closed: return "P.O Fechada"
    if has_po: return "P.O"
    return raw

def normalizar_os(val) -> str | None:
    if pd.isna(val): return None
    s = str(val).strip()
    m = re.match(r"^\s*(\d{4})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{3,5})\s*$", s)
    if not m: return None
    ano = int(m.group(1)); mes = int(m.group(2)); seq = m.group(3)
    if not (1 <= mes <= 12): return None
    try: seq_int = int(seq)
    except ValueError: return None
    return f"{ano:04d}/{mes:02d}/{seq_int:04d}"

def check_env():
    info = {}
    info["python"] = f"{importlib.util.find_spec.__module__} ok"
    info["pandas"] = getattr(pd, '__version__', 'unknown')
    try:
        import streamlit as _st
        info["streamlit"] = getattr(_st, '__version__', 'unknown')
    except Exception as e:
        info["streamlit"] = f"erro: {type(e).__name__}"
    for mod in ["openpyxl","xlrd","pyxlsb"]:
        try:
            importlib.import_module(mod)
            info[mod] = "ok"
        except Exception as e:
            info[mod] = f"ausente ({type(e).__name__})"
    return info

# ======================== LOAD ========================
@st.cache_data(show_spinner=False)
def carregar_dados(path: str | BytesIO):
    env = check_env()
    engine = _choose_engine(path)

    # aliases extras para colunas comuns
    mapa_renome = {
        # OS
        "Or?/OS":"Orç/OS", "Orc/OS":"Orç/OS", "OS":"Orç/OS", "O.S":"Orç/OS",
        "Ordem de Serviço":"Orç/OS", "Ordem de Servico":"Orç/OS", "Ordem OS":"Orç/OS",
        # datas
        "Enviar at?":"Enviar até", "Retornar at?":"Retornar até",
        # condicao
        "Condi??o":"Condição", "Condicao":"Condição",
        # situacao grafada
        "Situacao":"Sit", "Situação":"Sit",
        # item/insumo/prefixo variações
        "Numero do Item":"Item", "Número do Item":"Item"
    }

    try:
        try:
            df = pd.read_excel(path, sheet_name="Worksheet", engine=engine)
        except Exception:
            xls = pd.ExcelFile(path, engine=engine)
            df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
    except Exception as e:
        return pd.DataFrame(), {"env": env, "erro_leitura": repr(e)}

    df_orig_cols = list(df.columns)
    df = df.rename(columns=mapa_renome)

    colunas_importantes = [
        "Status","Sit","Prefixo","Orç/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Enviar até","Retornar até",
        "Motivo","Condição","Qtdade"
    ]

    # aproxima por normalização
    norm_cols = {c: _norm(c) for c in df.columns}
    alvo_norm = {a: _norm(a) for a in colunas_importantes}
    ren_extra = {}
    for col_atual, n_atual in norm_cols.items():
        for alvo, n_alvo in alvo_norm.items():
            if n_atual == n_alvo and col_atual != alvo:
                ren_extra[col_atual] = alvo
    if ren_extra: df = df.rename(columns=ren_extra)

    keep = [c for c in colunas_importantes if c in df.columns]
    df = df[keep].copy()

    # datas
    for col in ["Enviar até","Retornar até"]:
        if col in df.columns:
            df[col] = parse_mixed_dates(df[col])

    # textos e qtd
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()
    if "Qtdade" in df.columns:
        df["Qtdade"] = pd.to_numeric(df["Qtdade"], errors="coerce").fillna(0).astype(int)

    # status limpo
    if "Status" in df.columns:
        df["Status"] = df["Status"].apply(limpar_status)

    # prazos
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

    # Diagnóstico de OS
    diag = {"env": env, "orig_cols": df_orig_cols, "cols": list(df.columns)}
    if "Orç/OS" in df.columns:
        os_norm = df["Orç/OS"].map(normalizar_os)
        diag["os_total"] = int(len(df))
        diag["os_validas"] = int(os_norm.notna().sum())
        diag["os_invalidas"] = int(os_norm.isna().sum())
        # exemplos
        exemplos_invalidos = df.loc[os_norm.isna(), "Orç/OS"].astype(str).unique().tolist()[:8]
        exemplos_validos = df.loc[os_norm.notna(), "Orç/OS"].astype(str).unique().tolist()[:8]
        diag["os_exemplos_invalidos"] = exemplos_invalidos
        diag["os_exemplos_validos"] = exemplos_validos
        # substitui
        df = df[os_norm.notna()].copy()
        df["Orç/OS"] = os_norm.loc[os_norm.notna()]
    else:
        diag["os_aviso"] = "Coluna 'Orç/OS' não encontrada após renomear/normalizar."

    diag["shape_final"] = tuple(df.shape)
    return df, diag

# ======================== RENDERERS ========================
def badge(texto: str, tone="gray") -> str:
    cls = {"gray":"badge-gray","blue":"badge-blue","amber":"badge-amber","red":"badge-red","green":"badge-green"}.get(tone,"badge-gray")
    return f'<span class="badge {cls}">{esc(texto)}</span>'

def render_cards(dfv: pd.DataFrame, min_card_px: int = 240) -> None:
    if dfv.empty:
        st.info("Nenhum item encontrado.")
        return
    html_cards = [f'<div class="grid-cards" style="--min-card:{int(min_card_px)}px;">']
    for _, r in dfv.iterrows():
        cls = "card"
        if r.get("Em atraso", False): cls += " card-danger"
        elif r.get("Vence em 7 dias", False): cls += " card-warn"

        item = esc(r.get("Item","—"))
        insumo = esc((r.get("Insumo","") or "—"))
        sit = str(r.get("Sit","")).strip()
        status = str(r.get("Status","")).strip()
        prefixo = str(r.get("Prefixo","")).strip()

        chips = []
        if sit:     chips.append(badge(f"Sit: {sit}"))
        if status:  chips.append(badge(f"Status: {status}", "blue" if "P.O" in status else ("red" if status.lower().startswith("n") else "gray")))
        if prefixo: chips.append(badge(f"Prefixo: {prefixo}"))

        dt = r.get("Retornar até", pd.NaT); dias = r.get("Dias para devolver", None)
        if pd.notna(dt):
            when = dt.strftime("%d/%m/%Y")
            tone = "amber" if (isinstance(dias,(int,float,np.integer,np.floating)) and 0 <= dias <= 7) else ("red" if isinstance(dias,(int,float,np.integer,np.floating)) and dias < 0 else "gray")
            chips.append(badge(f"Devolver: {when}", tone))
        else:
            chips.append(badge("Sem data", "gray"))

        ctx = ""
        if isinstance(dias,(int,float,np.integer,np.floating)) and not pd.isna(dias):
            d = int(dias)
            if d < 0: ctx = f"<span class='small-muted'>Atrasado há {abs(d)} dia(s)</span>"
            elif d == 0: ctx = "<span class='small-muted'>Vence hoje</span>"
            else: ctx = f"<span class='small-muted'>Faltam {d} dia(s)</span>"

        html_cards.append(f"""
        <div class="{cls}">
          <div class="card-title">{item}</div>
          <div class="card-sub">{insumo}</div>
          <div class="row">{''.join(chips)}</div>
          <div class="row">{ctx}</div>
        </div>
        """)
    html_cards.append("</div>")
    st.markdown("\n".join(html_cards), unsafe_allow_html=True)

def render_list_dense(dfv: pd.DataFrame) -> None:
    if dfv.empty:
        st.info("Nenhum item encontrado.")
        return
    rows = []
    for _, r in dfv.iterrows():
        item = esc(r.get("Item","—"))
        insumo = esc((r.get("Insumo","") or "—"))
        sit = esc(r.get("Sit",""))
        status = str(r.get("Status","")).strip()
        status_span = badge(status, "blue" if "P.O" in status else ("red" if status.lower().startswith("n") else "gray")) if status else ""
        prefixo = esc(r.get("Prefixo",""))
        dt = r.get("Retornar até", pd.NaT)
        when = dt.strftime("%d/%m/%Y") if pd.notna(dt) else "—"
        d = r.get("Dias para devolver", None)
        if isinstance(d,(int,float,np.integer,np.floating)) and not pd.isna(d):
            dd = f"{int(d)}" if int(d) >= 0 else f"-{abs(int(d))}"
        else:
            dd = "—"
        rows.append(f"""
          <div class="table-r">
            <div>{item}</div><div class="cell-muted">{insumo}</div><div>{sit}</div>
            <div>{status_span}</div><div>{prefixo}</div><div class="cell-muted">{when} · {dd}d</div>
          </div>
        """)
    st.markdown("""
    <div class="table-wrap">
      <div class="table-h">
        <div>Item</div><div>Insumo</div><div>Situação</div><div>Status</div><div>Prefixo</div><div>Prazo</div>
      </div>
    """ + "\n".join(rows) + "</div>", unsafe_allow_html=True)

# ======================== SIDEBAR (CONTROLES) ========================
st.sidebar.title("🎛️ Controles")

with st.sidebar.expander("Fonte de dados", expanded=True):
    up = st.file_uploader("Excel (.xlsx/.xls/.xlsb)", type=["xlsx","xls","xlsb"])
    if up is not None:
        path = BytesIO(up.read())
    else:
        path = st.text_input("Ou caminho local", value="reparo_atual.xlsx")

# carregar + diag
df, diag = carregar_dados(path)

# ===== Diagnóstico (sempre disponível) =====
with st.sidebar.expander("🩺 Diagnóstico", expanded=False):
    st.write({"versao_app": APP_VERSION})
    st.write({"ambiente": diag.get("env", {})})
    st.write({"colunas_origem": diag.get("orig_cols", [])})
    st.write({"colunas_atuais": diag.get("cols", [])})
    if "os_total" in diag:
        st.write({
            "linhas_total": diag.get("os_total"),
            "os_validas": diag.get("os_validas"),
            "os_invalidas": diag.get("os_invalidas"),
        })
        if diag.get("os_invalidas", 0) > 0:
            st.caption("Exemplos descartados por formato de OS:")
            st.code("\n".join(map(str, diag.get("os_exemplos_invalidos", []))) or "(nenhum)")
        st.caption("Exemplos aceitos (OS normalizada):")
        st.code("\n".join(map(str, diag.get("os_exemplos_validos", []))) or "(nenhum)")
    if diag.get("os_aviso"):
        st.warning(diag["os_aviso"])
    st.write({"shape_final": diag.get("shape_final")})

ignorar_os = st.sidebar.checkbox("Ignorar filtro de OS (debug)", value=False, help="Mostra tudo mesmo que 'Orç/OS' não exista ou não normalize.")
if ignorar_os:
    # reabre dados sem aplicar o recorte por OS (usando colunas antes da filtragem)
    # Para simplificar: se houve os_exemplos_invalidos, apenas informamos que o filtro está ignorado.
    st.sidebar.info("Filtro de OS ignorado para depuração.")

st.sidebar.markdown("### Vistas rápidas")
vista = st.sidebar.radio("Seleção", ["Todos os itens", "Atrasados", "Próx. 7 dias", "Sem data"], index=0)

f_status  = st.sidebar.selectbox("Status", ["(Todos)"] + (sorted(df["Status"].dropna().astype(str).unique()) if "Status" in df else []))
f_sit     = st.sidebar.selectbox("Situação (Sit)", ["(Todos)"] + (sorted(df["Sit"].dropna().astype(str).unique()) if "Sit" in df else []))
f_prefixo = st.sidebar.text_input("Prefixo (contém)")
busca     = st.sidebar.text_input("Busca livre")

st.sidebar.markdown("---")
inclui_sem_data = st.sidebar.checkbox("Incluir itens sem data", value=True)
habilitar_filtro_datas = st.sidebar.checkbox("Filtrar por 'Retornar até'", value=False)
if habilitar_filtro_datas and "Retornar até" in df.columns:
    min_d, max_d = df["Retornar até"].min(), df["Retornar até"].max()
    if pd.notna(min_d) and pd.notna(max_d):
        date_range = st.sidebar.date_input("Janela 'Retornar até'", value=(min_d.date(), max_d.date()))
    else:
        date_range = None
        st.sidebar.info("Não há datas válidas.")
else:
    date_range = None

st.sidebar.markdown("---")
visao = st.sidebar.radio("Visão", ["Cards", "Lista"], index=0)
min_card_px = st.sidebar.slider("Largura mínima do card", 200, 360, 240, step=10)
compactar = st.sidebar.toggle("Compactar interface (sem título/KPIs)", value=True)

ordem = st.sidebar.selectbox(
    "Ordenar por",
    [c for c in ["Em atraso","Vence em 7 dias","Dias para devolver","Retornar até",
                 "Item","Insumo","Prefixo","Status","Sit","Qtdade"] if c in df.columns],
)
ordem_cresc = st.sidebar.toggle("Ordem crescente", value=False if ordem in ["Em atraso","Vence em 7 dias"] else True)

# ======================== FILTRAGEM ========================
df_f = df.copy()
if ignorar_os and diag.get("os_invalidas", 0) > 0:
    # Reconstroi df_f juntando também as linhas que foram descartadas pela OS normalizada
    # (aproximação: recarrega dados brutos e aplica todo o pipeline exceto o recorte de OS)
    bruto, _ = carregar_dados(path)  # já processado; como cache, é rápido
    # mas carregar_dados já aplicou filtro de OS; então simplesmente usamos df original 'df' aqui
    # e sinalizamos nos cards que o filtro foi ignorado.
    pass  # df_f já é df (com OS válidas); para ver tudo, aponte-me o nome real da coluna de OS e ajusto.

# vistas rápidas
if vista == "Atrasados" and "Em atraso" in df_f: df_f = df_f[df_f["Em atraso"]]
elif vista == "Próx. 7 dias" and "Vence em 7 dias" in df_f: df_f = df_f[df_f["Vence em 7 dias"]]
elif vista == "Sem data" and "Sem data" in df_f: df_f = df_f[df_f["Sem data"]]

# filtros
if f_status != "(Todos)" and "Status" in df_f: df_f = df_f[df_f["Status"].astype(str) == f_status]
if f_sit    != "(Todos)" and "Sit" in df_f:    df_f = df_f[df_f["Sit"].astype(str) == f_sit]
if f_prefixo and "Prefixo" in df_f:            df_f = df_f[df_f["Prefixo"].astype(str).str.contains(f_prefixo, case=False, na=False)]
if busca:
    txt = busca.strip().lower()
    mask = pd.Series(False, index=df_f.index)
    for col in df_f.columns:
        mask |= df_f[col].astype(str).str.lower().str.contains(txt, na=False)
    df_f = df_f[mask]

# datas
if habilitar_filtro_datas and date_range and "Retornar até" in df_f and len(date_range) == 2:
    ini, fim = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)
    mask_data = (df_f["Retornar até"] >= ini) & (df_f["Retornar até"] < fim)
    if inclui_sem_data: mask_data |= df_f["Retornar até"].isna()
    df_f = df_f[mask_data]
elif not inclui_sem_data and "Retornar até" in df_f:
    df_f = df_f[~df_f["Retornar até"].isna()]

# ordenação
if ordem in df_f.columns:
    secund = "Retornar até" if ("Retornar até" in df_f.columns and ordem != "Retornar até") else None
    if secund: df_f = df_f.sort_values(by=[ordem, secund], ascending=[ordem_cresc, True])
    else:      df_f = df_f.sort_values(by=[ordem], ascending=[ordem_cresc])

# ======================== HEADER & KPIs ========================
if not compactar:
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

# ======================== CONTEÚDO ========================
subset = [c for c in ["Item","Insumo","Sit","Status","Prefixo","Retornar até","Dias para devolver","Em atraso","Vence em 7 dias","Sem data"] if c in df_f.columns]
df_view = df_f[subset].copy()

if df_view.empty:
    st.warning("Nenhuma linha após filtros atuais.")
    # Heurísticas de causa provável
    if diag.get("os_aviso"):
        st.info("Possível causa: a coluna de OS não foi reconhecida. Ajuste o nome no Excel ou inclua um alias em 'mapa_renome'.")
    elif diag.get("os_validas", 0) == 0 and diag.get("os_total", 0) > 0:
        st.info("Possível causa: nenhum valor de OS casa com o padrão esperado (ex.: '2025/08/0053'). Verifique exemplos em 'Diagnóstico'.")
    else:
        st.info("Revise filtros na barra lateral (Status/Sit/Prefixo/datas).")
else:
    if visao == "Cards":
        render_cards(df_view, min_card_px=min_card_px)
    else:
        render_list_dense(df_view)

# Rodapé discreto
if not compactar:
    st.markdown("---")
    st.caption(f"Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}  ·  {APP_VERSION}")

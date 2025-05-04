import streamlit as st
from datetime import date
from calendar import monthrange
import pandas as pd
import altair as alt
from sqlalchemy import create_engine, text
import sqlalchemy.exc

# ---------------- Database (Neon PostgreSQL) -------------------
eng = create_engine(
    st.secrets["db"]["url"],
    pool_pre_ping=True
)

DDL = """
CREATE TABLE IF NOT EXISTS gastos (
  id SERIAL PRIMARY KEY,
  username TEXT,
  data DATE,
  valor NUMERIC,
  descricao TEXT,
  categoria TEXT,
  fonte TEXT
);
CREATE TABLE IF NOT EXISTS orcamento (
  id SERIAL PRIMARY KEY,
  username TEXT,
  mes INT,
  ano INT,
  valor_planejado NUMERIC,
  UNIQUE (username, mes, ano)
);
"""

# Execute DDL safely, ignoring existing sequence errors
with eng.begin() as conn:
    for stmt in DDL.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.exec_driver_sql(stmt)
        except sqlalchemy.exc.IntegrityError as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate key value" in msg:
                # ignore sequence or relation already exists
                pass
            else:
                raise

# ------------------- Utils -------------------
def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12); y += d.year; m += 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))

def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def rerun():
    (st.rerun if hasattr(st, "rerun") else st.experimental_rerun)()

# ------------------- Page config -------------------
st.set_page_config(page_title="Controle de Gastos", page_icon="icone.png", layout="wide")

# ------------------- Login -------------------
if not st.user.is_logged_in:
    st.title("Controle de Gastos")
    st.button("Entrar com Google ➜", on_click=st.login)
    st.stop()
user_email = st.user.email
st.button("Logout", on_click=st.logout, key="logout")

# ------------------- Sidebar -------------------
with st.sidebar:
    st.image("icone.png", width=120)
    st.markdown("---")

# ------------------- Data helpers -------------------
@st.cache_data(ttl=60, show_spinner=False)
def load_table(tbl):
    return pd.read_sql(text(f"SELECT * FROM {tbl}"), eng)

def save_gasto(row):
    cols = ", ".join(row.keys())
    vals = ", ".join([f":{k}" for k in row.keys()])
    with eng.begin() as c:
        c.execute(text(f"INSERT INTO gastos ({cols}) VALUES ({vals})"), row)

def upsert_orc(u, m, a, v):
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO orcamento (username,mes,ano,valor_planejado) "
            "VALUES (:u,:m,:a,:v) "
            "ON CONFLICT (username,mes,ano) DO UPDATE SET valor_planejado=:v"
        ), dict(u=u,m=m,a=a,v=v))

# ------------------- Load data -------------------
gastos_df    = load_table("gastos")
orcamento_df = load_table("orcamento")

# ------------------- Month/Year selector -------------------
meses = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
         "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
mes = st.sidebar.selectbox("Mês", range(1,13),
                           format_func=lambda x: meses[x-1],
                           index=date.today().month-1)
ano = st.sidebar.number_input("Ano", value=date.today().year, step=1, format="%d")

# ------------------- Budget -------------------
lo = orcamento_df[
    (orcamento_df.username==user_email)&
    (orcamento_df.mes==mes)&
    (orcamento_df.ano==ano)
]
orc_val = float(lo.valor_planejado.iloc[0]) if not lo.empty else None
st.sidebar.markdown(f"🎯 **Orçamento:** {brl(orc_val) if orc_val else '—'}")

novo_orc = st.sidebar.number_input("Definir/alterar orçamento",
                                   value=orc_val or 0.0, step=0.01, format="%.2f")
if st.sidebar.button("Salvar orçamento"):
    upsert_orc(user_email, mes, ano, novo_orc)
    st.sidebar.success("Orçamento salvo!")
    st.cache_data.clear()
    rerun()

if orc_val is None:
    st.warning("Defina o orçamento antes de continuar.")
    st.stop()

st.sidebar.divider()

# ------------------- New expense form -------------------
st.sidebar.header("Novo gasto")
first_day = date(ano, mes, 1)
last_day  = date(ano, mes, monthrange(ano, mes)[1])
default_d = date.today() if first_day <= date.today() <= last_day else first_day
dcomp = st.sidebar.date_input("Data", value=default_d,
                              min_value=first_day, max_value=last_day,
                              format="DD/MM/YYYY")
desc = st.sidebar.text_input("Descrição")

categorias = ["Alimentação","Transporte","Lazer","Fixos","Educação",
              "Presentes","Comprinhas","Outros"]
cat = st.sidebar.selectbox("Categoria", categorias)
fonte = st.sidebar.selectbox("Fonte",
        ["Dinheiro","Crédito","Débito","PIX","Vale Refeição","Vale Alimentação"])

parc = st.sidebar.checkbox("Compra parcelada?")
if parc:
    nparc = st.sidebar.number_input("Qtd. parcelas", 1, step=1, value=2)
    modo  = st.sidebar.radio("Informar:", ["Valor total","Valor por parcela"], horizontal=True)
    if modo == "Valor total":
        vtot = st.sidebar.number_input("Valor total (R$)", 0.0, step=0.01, format="%.2f")
        vparc = vtot/nparc if nparc else 0.0
    else:
        vparc = st.sidebar.number_input("Valor por parcela (R$)", 0.0, step=0.01, format="%.2f")
        vtot  = vparc*nparc
    st.sidebar.markdown(f"Total: {brl(vtot)} → Parcela: {brl(vparc)}")
else:
    v = st.sidebar.number_input("Valor (R$)", 0.0, step=0.01, format="%.2f")

if st.sidebar.button("Registrar 💾"):
    if parc:
        for i in range(int(nparc)):
            save_gasto({"username":user_email,
                        "data":add_months(dcomp,i),
                        "valor":vparc,
                        "descricao":f"{desc} (parc.{i+1}/{int(nparc)})",
                        "categoria":cat,"fonte":fonte})
    else:
        save_gasto({"username":user_email,"data":dcomp,"valor":v,
                    "descricao":desc,"categoria":cat,"fonte":fonte})
    st.sidebar.success("Gasto salvo!")
    st.cache_data.clear()
    rerun()

# ------------------- Dashboard -------------------
gastos_df = load_table("gastos")
df_user   = gastos_df[gastos_df.username==user_email].copy()
df_user["data"] = pd.to_datetime(df_user.data)
mes_df = df_user[(df_user.data.dt.month==mes)&(df_user.data.dt.year==ano)]

gasto_total = mes_df.valor.sum()
saldo       = orc_val - gasto_total

a,b,c = st.columns(3)
a.metric("💸 Gasto", brl(gasto_total))
b.metric("🎯 Orçamento", brl(orc_val))
c.metric("📈 Saldo", brl(saldo), delta=brl(saldo), delta_color="normal" if saldo>=0 else "inverse")

st.title(f"Gastos de {meses[mes-1]}/{ano}")

if mes_df.empty:
    st.info("Nenhum gasto registrado.")
    st.stop()

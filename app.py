import streamlit as st
from datetime import date
from calendar import monthrange
import pandas as pd
import altair as alt
from sqlalchemy import create_engine, text
import sqlalchemy.exc

# ─── Database setup ────────────────────────────────────────────────
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
with eng.begin() as conn:
    for stmt in DDL.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.exec_driver_sql(stmt)
        except sqlalchemy.exc.IntegrityError as e:
            if "already exists" in str(e).lower():
                pass
            else:
                raise

# ─── Utils ─────────────────────────────────────────────────────────
def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year; m += 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))

def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def rerun():
    (st.rerun if hasattr(st, 'rerun') else st.experimental_rerun)()

# ─── Page config ──────────────────────────────────────────────────
st.set_page_config(page_title="Controle de Gastos", page_icon="icone.png", layout="wide")

# ─── Auth ──────────────────────────────────────────────────────────
if not st.user.is_logged_in:
    st.title("Controle de Gastos")
    st.button("Entrar com Google ➜", on_click=st.login)
    st.stop()
user = st.user.email
st.button("Logout", on_click=st.logout)

# ─── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.image("icone.png", width=120)
    st.markdown("---")

# ─── Data helpers ──────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_table(name):
    return pd.read_sql(text(f"SELECT * FROM {name}"), eng)

def insert_gasto(data):
    cols = ", ".join(data.keys())
    vals = ", ".join([f":{k}" for k in data.keys()])
    with eng.begin() as c:
        c.execute(text(f"INSERT INTO gastos ({cols}) VALUES ({vals})"), data)

def upsert_orc(u,m,a,v):
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO orcamento (username,mes,ano,valor_planejado) "
            "VALUES (:u,:m,:a,:v) ON CONFLICT (username,mes,ano) DO UPDATE "
            "SET valor_planejado=:v"
        ), dict(u=u,m=m,a=a,v=v))

# ─── Load data ─────────────────────────────────────────────────────
gastos_df = load_table("gastos")
orc_df    = load_table("orcamento")

# ─── Month/Year selector ───────────────────────────────────────────
meses = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
         "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
mes = st.sidebar.selectbox("Mês", list(range(1,13)), format_func=lambda x: meses[x-1],
                            index=date.today().month-1)
ano = st.sidebar.number_input("Ano", value=date.today().year, step=1, format="%d")

# ─── Budget ────────────────────────────────────────────────────────
row = orc_df[(orc_df.username==user)&(orc_df.mes==mes)&(orc_df.ano==ano)]
orc_val = float(row.valor_planejado.iloc[0]) if not row.empty else None
st.sidebar.markdown(f"**Orçamento:** {brl(orc_val) if orc_val else '–'}")

novo = st.sidebar.number_input("Definir orçamento", value=orc_val or 0.0, step=0.01, format="%.2f")
if st.sidebar.button("Salvar orçamento"):
    upsert_orc(user, mes, ano, novo)
    st.sidebar.success("Orçamento salvo!")
    st.cache_data.clear()
    rerun()
if orc_val is None:
    st.warning("Defina o orçamento antes."); st.stop()
st.sidebar.divider()

# ─── New expense ───────────────────────────────────────────────────
st.sidebar.header("Novo gasto")
first = date(ano,mes,1); last = date(ano,mes,monthrange(ano,mes)[1])
default = date.today() if first<=date.today()<=last else first
d = st.sidebar.date_input("Data", value=default, min_value=first, max_value=last, format="DD/MM/YYYY")
desc = st.sidebar.text_input("Descrição")
cats = ["Alimentação","Transporte","Lazer","Fixos","Educação","Presentes","Comprinhas","Outros"]
cat = st.sidebar.selectbox("Categoria", cats)
fonte = st.sidebar.selectbox("Fonte", ["Dinheiro","Crédito","Débito","PIX","Vale Refeição","Vale Alimentação"])
parc = st.sidebar.checkbox("Compra parcelada?")
if parc:
    n = st.sidebar.number_input("Qtde parcelas",1,step=1,value=2)
    modo = st.sidebar.radio("Informar:",["Total","Parcela"],horizontal=True)
    if modo=="Total":
        vt = st.sidebar.number_input("Total R$",0.0,step=0.01,format="%.2f"); vp = vt/n
    else:
        vp = st.sidebar.number_input("Parcela R$",0.0,step=0.01,format="%.2f"); vt = vp*n
    st.sidebar.markdown(f"Total: {brl(vt)} → Parcela: {brl(vp)}")
else:
    vp = st.sidebar.number_input("Valor R$",0.0,step=0.01,format="%.2f"); vt=vp; n=1
if st.sidebar.button("Registrar"):
    for i in range(int(n)):
        insert_gasto({
            "username":user,
            "data":add_months(d,i),
            "valor":vp,
            "descricao":f"{desc} ({i+1}/{int(n)})",
            "categoria":cat,
            "fonte":fonte
        })
    st.sidebar.success("Gasto salvo!"); st.cache_data.clear(); rerun()

# ─── Dashboard summary & charts ───────────────────────────────────
df = gastos_df[gastos_df.username==user].copy()
df["data"] = pd.to_datetime(df.data)
sel = df[(df.data.dt.month==mes)&(df.data.dt.year==ano)]
gt = sel.valor.sum(); sd = orc_val - gt

c1,c2,c3 = st.columns(3)
c1.metric("💸 Gasto", brl(gt))
c2.metric("🎯 Orçamento", brl(orc_val))
c3.metric("📈 Saldo", brl(sd), delta=brl(sd), delta_color="normal" if sd>=0 else "inverse")

st.title(f"Gastos de {meses[mes-1]}/{ano}")
if sel.empty:
    st.info("Nenhum gasto."); st.stop()

# ─── Charts ───────────────────────────────────────────────────────
# Define explicit color mappings
cor_cat = {
    "Alimentação":"#1f77b4","Transporte":"#ff7f0e","Lazer":"#2ca02c",
    "Fixos":"#d62728","Educação":"#9467bd","Presentes":"#17becf",
    "Comprinhas":"#bcbd22","Outros":"#8c564b"
}
cor_ft = {
    "Dinheiro":"#1f77b4","Crédito":"#d62728","Débito":"#2ca02c",
    "PIX":"#ff7f0e","Vale Refeição":"#9467bd","Vale Alimentação":"#8c564b"
}
cor_sd = {"Gasto":"#e74c3c","Disponível":"#2ecc71"}

def make_donut(df, field, title, palette, legend_title):
    df_nonzero = df[df["valor"]>0]
    present = df_nonzero[field].tolist()
    chart = alt.Chart(df_nonzero).mark_arc(innerRadius=60).encode(
        theta="valor:Q",
        color=alt.Color(f"{field}:N", title=legend_title,
                        scale=alt.Scale(domain=present,
                                        range=[palette[k] for k in present]),
                        legend=alt.Legend(orient="left"))
    ).properties(title=title)
    return chart

df_cat = sel.groupby("categoria")[ "valor"].sum().reset_index()
df_ft = sel.groupby("fonte")["valor"].sum().reset_index()
df_sd = pd.DataFrame({"Status":["Gasto","Disponível"],"valor":[gt,max(sd,0)]})

chart1 = make_donut(df_cat,"categoria","Por categoria",cor_cat,"Categoria")
chart2 = make_donut(df_ft,"fonte","Por fonte",cor_ft,"Fonte")
chart3 = make_donut(df_sd,"Status","Disponibilidade",cor_sd,"Disponibilidade")

col1,col2,col3 = st.columns(3)
col1.altair_chart(chart1,use_container_width=True)
col2.altair_chart(chart2,use_container_width=True)
col3.altair_chart(chart3,use_container_width=True)

# ─── Detailed list ───────────────────────────────────────────────
st.subheader("📜 Registros detalhados")
if "del_id" not in st.session_state:
    st.session_state.del_id=None

for _, r in sel.sort_values("data",ascending=False).iterrows():
    cols = st.columns([1.2,3,2,1.2,1.2,0.6])
    cols[0].write(r.data.strftime("%d/%m/%Y"))
    cols[1].write(r.descricao)
    cols[2].write(r.categoria)
    cols[3].write(r.fonte)
    cols[4].write(brl(r.valor))
    if cols[5].button("🗑️",key=f"del{r.id}"):
        st.session_state.del_id=r.id
    if st.session_state.del_id==r.id:
        st.warning(f"Apagar {r.descricao} ({r.data.strftime('%d/%m/%Y')}, {brl(r.valor)})?")
        c_ok,c_no = st.columns(2)
        if c_ok.button("✅",key=f"ok{r.id}"):
            with eng.begin() as c:
                c.exec_driver_sql("DELETE FROM gastos WHERE id=:id",{"id":r.id})
            st.session_state.del_id=None; rerun()
        if c_no.button("❌",key=f"no{r.id}"):
            st.session_state.del_id=None; rerun()

import streamlit as st
from datetime import date
from calendar import monthrange
import pandas as pd
import altair as alt                    # usado para os gráficos
from sqlalchemy import create_engine, text

# ────── utilidades ───────────────────────────────────────────────
def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12); y += d.year; m += 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))

def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def rerun():
    (st.rerun if hasattr(st, "rerun") else st.experimental_rerun)()

# ────── configuração ─────────────────────────────────────────────
st.set_page_config("Controle de Gastos", "💸", layout="wide")

# ────── LOGIN COM GOOGLE ─────────────────────────────────────────
if not st.user.is_logged_in:
    st.title("Controle de Gastos")
    st.write("Entre para acessar seus dados.")
    st.button("Entrar com Google ➜", on_click=st.login)
    st.stop()
else:
    st.button("Logout", on_click=st.logout, key="logout")
    user_email = st.user.email           # chave no banco

# ────── banco SQLite ─────────────────────────────────────────────
eng = create_engine("sqlite:///gastos.db",
                    connect_args={"check_same_thread": False})
with eng.begin() as c:
    c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS gastos(
        id INTEGER PRIMARY KEY,
        username TEXT, data TEXT,
        valor REAL, descricao TEXT, categoria TEXT, fonte TEXT)""")
    c.exec_driver_sql("""CREATE TABLE IF NOT EXISTS orcamento(
        id INTEGER PRIMARY KEY, username TEXT,
        mes INTEGER, ano INTEGER, valor_planejado REAL,
        UNIQUE(username,mes,ano))""")

# ────── seleção mês/ano ─────────────────────────────────────────
meses = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
         "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
mes = st.sidebar.selectbox("Mês", range(1,13),
                           format_func=lambda x: meses[x-1],
                           index=date.today().month-1)
ano = st.sidebar.number_input("Ano", value=date.today().year,
                              step=1, format="%d")

# ────── orçamento ───────────────────────────────────────────────
with eng.begin() as c:
    row = c.execute(text("SELECT valor_planejado FROM orcamento "
                         "WHERE username=:u AND mes=:m AND ano=:a"),
                    dict(u=user_email,m=mes,a=ano)).fetchone()
orc = row[0] if row else None
st.sidebar.markdown(f"🎯 **Orçamento:** {brl(orc) if orc else '—'}")
novo_orc = st.sidebar.number_input("Definir/alterar orçamento",
                                   value=orc or 0.0, step=0.01,
                                   format="%.2f")
if st.sidebar.button("Salvar orçamento"):
    with eng.begin() as c:
        c.execute(text("INSERT OR REPLACE INTO orcamento "
                       "(username,mes,ano,valor_planejado)"
                       "VALUES(:u,:m,:a,:v)"),
                  dict(u=user_email,m=mes,a=ano,v=novo_orc))
    st.sidebar.success("Orçamento salvo!"); rerun()

if orc is None:
    st.warning("Defina o orçamento antes de continuar."); st.stop()

st.sidebar.divider()

# ────── formulário novo gasto ───────────────────────────────────
st.sidebar.header("Novo gasto")
first_day = date(ano, mes, 1)
last_day  = date(ano, mes, monthrange(ano, mes)[1])
default_d = date.today()
if not (first_day <= default_d <= last_day):
    default_d = first_day

dcomp = st.sidebar.date_input("Data", value=default_d,
                              min_value=first_day,
                              max_value=last_day,
                              format="DD/MM/YYYY")
desc  = st.sidebar.text_input("Descrição")
cat   = st.sidebar.selectbox("Categoria",
         ["Alimentação","Transporte","Lazer",
          "Fixos","Educação","Comprinhas","Presente","Saúde","Outros"])
fonte = st.sidebar.selectbox("Fonte",
         ["Dinheiro","Crédito","Débito","PIX",
          "Vale Refeição","Vale Alimentação"])

parc = st.sidebar.checkbox("Compra parcelada?")
if parc:
    nparc = st.sidebar.number_input("Qtd. parcelas", 1, step=1, value=2)
    modo  = st.sidebar.radio("Informar:",
                             ["Valor total", "Valor por parcela"],
                             horizontal=True)
    if modo == "Valor total":
        vtot  = st.sidebar.number_input("Valor total (R$)", 0.0,
                                        step=0.01, format="%.2f")
        vparc = vtot / nparc if nparc else 0.0
    else:
        vparc = st.sidebar.number_input("Valor por parcela (R$)", 0.0,
                                        step=0.01, format="%.2f")
        vtot  = vparc * nparc
    total_txt   = brl(vtot).replace("$", "\\$")
    parcela_txt = brl(vparc).replace("$", "\\$")
    st.sidebar.markdown(
        f"Total: {total_txt} → Parcela: {parcela_txt}")
else:
    v = st.sidebar.number_input("Valor (R$)", 0.0, step=0.01, format="%.2f")

if st.sidebar.button("Registrar 💾"):
    with eng.begin() as c:
        if parc:
            for i in range(int(nparc)):
                d = add_months(dcomp, i)
                c.execute(text("INSERT INTO gastos "
                               "(username,data,valor,descricao,categoria,fonte)"
                               "VALUES(:u,:d,:v,:de,:ca,:fo)"),
                          dict(u=user_email,d=d.isoformat(),v=vparc,
                               de=f"{desc} (parc.{i+1}/{int(nparc)})",
                               ca=cat,fo=fonte))
        else:
            c.execute(text("INSERT INTO gastos "
                           "(username,data,valor,descricao,categoria,fonte)"
                           "VALUES(:u,:d,:v,:de,:ca,:fo)"),
                      dict(u=user_email,d=dcomp.isoformat(),v=v,
                           de=desc,ca=cat,fo=fonte))
    st.sidebar.success("Gasto salvo!"); rerun()

# ────── dados filtrados ─────────────────────────────────────────
df = pd.read_sql(text("SELECT * FROM gastos WHERE username=:u"),
                 eng, params=dict(u=user_email), parse_dates=["data"])
mes_df = df[(df.data.dt.month==mes)&(df.data.dt.year==ano)]

gasto = mes_df.valor.sum(); saldo = orc-gasto
a,b,c = st.columns(3)
a.metric("💸 Gasto", brl(gasto))
b.metric("🎯 Orçamento", brl(orc))
c.metric("📈 Saldo", brl(saldo),
         delta=brl(saldo),
         delta_color="normal" if saldo>=0 else "inverse")

st.title(f"Gastos de {meses[mes-1]}/{ano}")

if mes_df.empty:
    st.info("Nenhum gasto registrado."); st.stop()

# ────── cores ───────────────────────────────────────────────────
cor_cat = {"Alimentação":"#1f77b4","Transporte":"#ff7f0e",
           "Lazer":"#2ca02c","Fixos":"#d62728",
           "Educação":"#9467bd","Outros":"#8c564b"}
cor_ft  = {"Dinheiro":"#1f77b4","Crédito":"#d62728","Débito":"#2ca02c",
           "PIX":"#ff7f0e","Vale Refeição":"#9467bd",
           "Vale Alimentação":"#8c564b"}

def donut(data, field, title, palette, legend_title):
    present = [k for k in palette if k in data[field].tolist()]
    return (alt.Chart(data).mark_arc(innerRadius=60)
            .encode(theta="valor:Q",
                    color=alt.Color(f"{field}:N",
                        title=legend_title,
                        scale=alt.Scale(domain=present,
                                        range=[palette[k] for k in present]),
                        legend=alt.Legend(orient="left")))
            .properties(title=title))

cat_df   = mes_df.groupby("categoria")["valor"].sum().reset_index()
fonte_df = mes_df.groupby("fonte")["valor"].sum().reset_index()

cat_chart   = donut(cat_df,   "categoria", "Por categoria",
                    cor_cat,  "Categoria")
fonte_chart = donut(fonte_df, "fonte",     "Por fonte",
                    cor_ft,   "Fonte")

saldo_vals = {"Gasto": gasto, "Disponível": max(saldo, 0)}
saldo_present = [k for k,vv in saldo_vals.items() if vv>0]
saldo_chart = (alt.Chart(pd.DataFrame({"Status": saldo_present,
                                       "Valor": [saldo_vals[k] for k in saldo_present]}))
    .mark_arc(innerRadius=60)
    .encode(theta="Valor:Q",
            color=alt.Color("Status:N",
                            title="Disponibilidade",
                            scale=alt.Scale(domain=saldo_present,
                                            range=["#e74c3c","#2ecc71"][:len(saldo_present)]),
                            legend=alt.Legend(orient="left")))
    .properties(title="Orçamento vs gasto"))

g1,g2,g3 = st.columns(3)
g1.altair_chart(cat_chart,use_container_width=True)
g2.altair_chart(fonte_chart,use_container_width=True)
g3.altair_chart(saldo_chart,use_container_width=True)

st.subheader("📜 Registros detalhados")

# ────── exclusão inline ─────────────────────────────────────────
if "del_id" not in st.session_state: st.session_state.del_id=None

for _, r in mes_df.sort_values("data",ascending=False).iterrows():
    cols = st.columns([1.5,3,2,1.4,1.4,0.6])
    cols[0].write(r.data.strftime("%d/%m/%Y"))
    cols[1].write(r.descricao)
    cols[2].write(r.categoria)
    cols[3].write(r.fonte)
    cols[4].write(brl(r.valor))
    if cols[5].button("🗑️", key=f"del{r.id}"):
        st.session_state.del_id=int(r.id)

    if st.session_state.del_id == r.id:
        st.warning(f"Apagar **{r.descricao}** "
                   f"({r.data.strftime('%d/%m/%Y')}, {brl(r.valor)})?")
        c1,c2 = st.columns(2)
        if c1.button("✅ Confirmar", key=f"ok{r.id}"):
            with eng.begin() as c:
                c.execute(text("DELETE FROM gastos "
                               "WHERE id=:i AND username=:u"),
                          dict(i=r.id,u=user_email))
            st.session_state.del_id=None; rerun()
        if c2.button("❌ Cancelar", key=f"no{r.id}"):
            st.session_state.del_id=None; rerun()

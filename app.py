import json, streamlit as st
from datetime import date
from calendar import monthrange
import pandas as pd
import altair as alt
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from google.oauth2.service_account import Credentials

# ───────────── Helpers Google Sheets ─────────────────────────────
def _get_client():
    info = dict(st.secrets["gspread"]["service_account"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def _get_ws(name: str):
    gc = _get_client()
    sh = gc.open_by_key(st.secrets["gspread"]["sheet_id"])
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(name, rows=1000, cols=20)

@st.cache_data(ttl=60, show_spinner=False)
def load_df(sheet_name: str) -> pd.DataFrame:
    ws = _get_ws(sheet_name)
    df = get_as_dataframe(ws, evaluate_formulas=True, na_filter=False)
    df = df.dropna(how="all")                                     # remove linhas vazias
    if "id" in df.columns:
        df = df[df["id"].astype(str).str.strip() != ""]           # remove id vazio
        if not df.empty:
            df["id"] = pd.to_numeric(df["id"], errors="coerce").dropna().astype(int)
    return df

def save_df(df: pd.DataFrame, sheet_name: str):
    set_with_dataframe(_get_ws(sheet_name), df, include_index=False)

# ───────────── Utilidades ────────────────────────────────────────
def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12); y += d.year; m += 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))

def brl(v): return "R$ "+f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
def rerun(): (st.rerun if hasattr(st,"rerun") else st.experimental_rerun)()

# ───────────── Config. de página ─────────────────────────────────
st.set_page_config("Controle de Gastos", "icone.png", layout="wide")

# ───────────── Login Google ─────────────────────────────────────
if not st.user.is_logged_in:
    st.title("Controle de Gastos")
    st.button("Entrar com Google ➜", on_click=st.login)
    st.stop()
user_email = st.user.email
st.button("Logout", on_click=st.logout, key="logout")

# ───────────── Logo ─────────────────────────────────────────────
with st.sidebar:
    st.image("icone.png", width=120)
    st.markdown("---")

# ───────────── Dados ────────────────────────────────────────────
gastos_df    = load_df("gastos")
orcamento_df = load_df("orcamento")

meses = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
         "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
mes = st.sidebar.selectbox("Mês", range(1,13),
                           format_func=lambda x: meses[x-1],
                           index=date.today().month-1)
ano = st.sidebar.number_input("Ano", value=date.today().year, step=1, format="%d")

linha_orc = orcamento_df[
    (orcamento_df.username==user_email)&(orcamento_df.mes==mes)&(orcamento_df.ano==ano)]
orc_val = float(linha_orc.valor_planejado.iloc[0]) if not linha_orc.empty else None
st.sidebar.markdown(f"🎯 **Orçamento:** {brl(orc_val) if orc_val else '—'}")

novo_orc = st.sidebar.number_input("Definir/alterar orçamento", value=orc_val or 0.0,
                                   step=0.01, format="%.2f")
if st.sidebar.button("Salvar orçamento"):
    if linha_orc.empty:
        orcamento_df = pd.concat([orcamento_df, pd.DataFrame([{
            "username":user_email,"mes":mes,"ano":ano,"valor_planejado":novo_orc}])],
            ignore_index=True)
    else:
        orcamento_df.loc[linha_orc.index[0],"valor_planejado"]=novo_orc
    save_df(orcamento_df,"orcamento")
    st.sidebar.success("Orçamento salvo!"); rerun()

if orc_val is None:
    st.warning("Defina o orçamento antes de continuar."); st.stop()

st.sidebar.divider()

# ───────────── Formulário ───────────────────────────────────────
st.sidebar.header("Novo gasto")
first_day,last_day = date(ano,mes,1),date(ano,mes,monthrange(ano,mes)[1])
default_d = date.today() if first_day<=date.today()<=last_day else first_day
dcomp = st.sidebar.date_input("Data", value=default_d,
                              min_value=first_day, max_value=last_day,
                              format="DD/MM/YYYY")
desc = st.sidebar.text_input("Descrição")

categorias = ["Alimentação","Transporte","Lazer","Fixos","Educação",
              "Presentes","Comprinhas","Outros"]          # ← adição aqui
cat   = st.sidebar.selectbox("Categoria", categorias)

fonte = st.sidebar.selectbox("Fonte",
         ["Dinheiro","Crédito","Débito","PIX",
          "Vale Refeição","Vale Alimentação"])

parc = st.sidebar.checkbox("Compra parcelada?")
if parc:
    nparc = st.sidebar.number_input("Qtd. parcelas",1,step=1,value=2)
    modo  = st.sidebar.radio("Informar:",["Valor total","Valor por parcela"],
                             horizontal=True)
    if modo=="Valor total":
        vtot = st.sidebar.number_input("Valor total (R$)",0.0,step=0.01,format="%.2f")
        vparc = vtot/nparc if nparc else 0
    else:
        vparc = st.sidebar.number_input("Valor por parcela (R$)",0.0,step=0.01,format="%.2f")
        vtot  = vparc*nparc
    st.sidebar.markdown(f"Total: {brl(vtot)} → Parcela: {brl(vparc)}")
else:
    v = st.sidebar.number_input("Valor (R$)",0.0,step=0.01,format="%.2f")

if st.sidebar.button("Registrar 💾"):
    next_id = 1 if gastos_df.empty else gastos_df.id.max()+1
    novas=[]
    if parc:
        for i in range(int(nparc)):
            d = add_months(dcomp,i)
            novas.append({"id":next_id+i,"username":user_email,"data":d.isoformat(),
                          "valor":vparc,"descricao":f"{desc} (parc.{i+1}/{int(nparc)})",
                          "categoria":cat,"fonte":fonte})
    else:
        novas.append({"id":next_id,"username":user_email,"data":dcomp.isoformat(),
                      "valor":v,"descricao":desc,"categoria":cat,"fonte":fonte})
    gastos_df = pd.concat([gastos_df,pd.DataFrame(novas)],ignore_index=True)
    save_df(gastos_df,"gastos")
    st.sidebar.success("Gasto salvo!"); rerun()

# ───────────── Filtro / Métricas ────────────────────────────────
df_user = gastos_df[gastos_df.username==user_email].copy()
df_user["data"]=pd.to_datetime(df_user.data)
mes_df  = df_user[(df_user.data.dt.month==mes)&(df_user.data.dt.year==ano)]

gasto_total = mes_df.valor.sum(); saldo = orc_val - gasto_total
a,b,c = st.columns(3)
a.metric("💸 Gasto", brl(gasto_total))
b.metric("🎯 Orçamento", brl(orc_val))
c.metric("📈 Saldo", brl(saldo),
         delta=brl(saldo), delta_color="normal" if saldo>=0 else "inverse")

st.title(f"Gastos de {meses[mes-1]}/{ano}")
if mes_df.empty:
    st.info("Nenhum gasto registrado."); st.stop()

# ───────────── Gráficos ─────────────────────────────────────────
cor_cat = {"Alimentação":"#1f77b4","Transporte":"#ff7f0e","Lazer":"#2ca02c",
           "Fixos":"#d62728","Educação":"#9467bd","Presentes":"#17becf",
           "Comprinhas":"#bcbd22","Outros":"#8c564b"}       # cores novas
cor_ft  = {"Dinheiro":"#1f77b4","Crédito":"#d62728","Débito":"#2ca02c",
           "PIX":"#ff7f0e","Vale Refeição":"#9467bd","Vale Alimentação":"#8c564b"}

def donut(df, field, title, palette, leg):
    present=[k for k in palette if k in df[field].tolist()]
    return (alt.Chart(df).mark_arc(innerRadius=60)
            .encode(theta="valor:Q",
                    color=alt.Color(f"{field}:N",title=leg,
                        scale=alt.Scale(domain=present,
                                        range=[palette[k] for k in present]),
                        legend=alt.Legend(orient="left")))
            .properties(title=title))

cat_chart   = donut(mes_df.groupby("categoria").valor.sum().reset_index(),
                    "categoria","Por categoria",cor_cat,"Categoria")
fonte_chart = donut(mes_df.groupby("fonte").valor.sum().reset_index(),
                    "fonte","Por fonte",cor_ft,"Fonte")
saldo_vals  = {"Gasto":gasto_total,"Disponível":max(saldo,0)}
saldo_pres  = [k for k,v in saldo_vals.items() if v>0]
saldo_chart = (alt.Chart(pd.DataFrame({"Status":saldo_pres,
                                       "Valor":[saldo_vals[k] for k in saldo_pres]}))
               .mark_arc(innerRadius=60)
               .encode(theta="Valor:Q",
                       color=alt.Color("Status:N", title="Disponibilidade",
                             scale=alt.Scale(domain=saldo_pres,
                                             range=["#e74c3c","#2ecc71"][:len(saldo_pres)]),
                             legend=alt.Legend(orient="left")))
               .properties(title="Orçamento vs gasto"))

g1,g2,g3 = st.columns(3)
g1.altair_chart(cat_chart, use_container_width=True)
g2.altair_chart(fonte_chart, use_container_width=True)
g3.altair_chart(saldo_chart, use_container_width=True)

# ───────────── Lista / Exclusão ─────────────────────────────────
st.subheader("📜 Registros detalhados")
if "del_id" not in st.session_state: st.session_state.del_id=None

for _,r in mes_df.sort_values("data",ascending=False).iterrows():
    c = st.columns([1.5,3,2,1.4,1.4,0.6])
    c[0].write(r.data.strftime("%d/%m/%Y"))
    c[1].write(r.descricao); c[2].write(r.categoria)
    c[3].write(r.fonte); c[4].write(brl(r.valor))
    if c[5].button("🗑️",key=f"del{r.id}"):
        st.session_state.del_id=int(r.id)
    if st.session_state.del_id==r.id:
        st.warning(f"Apagar **{r.descricao}** "
                   f"({r.data.strftime('%d/%m/%Y')}, {brl(r.valor)})?")
        c1,c2=st.columns(2)
        if c1.button("✅ Confirmar",key=f"ok{r.id}"):
            gastos_df=gastos_df[gastos_df.id!=r.id]
            save_df(gastos_df,"gastos"); st.session_state.del_id=None; rerun()
        if c2.button("❌ Cancelar",key=f"no{r.id}"):
            st.session_state.del_id=None; rerun()

"""

Dashboard — Custos de Producao da Soja (CONAB) — versao com IA (Ollama local)

Duplicata do app.py + botao de analise redigida por LLM local.



    streamlit run dashboard/app_ia.py



Requer Ollama instalado e rodando, e o modelo qwen2.5:3b baixado.

Sem o Ollama, o dashboard funciona normal; so o botao de IA avisa.

"""

import json

import sys

from pathlib import Path



import pandas as pd

import plotly.express as px

import plotly.graph_objects as go

import streamlit as st



sys.path.append(str(Path(__file__).resolve().parent.parent / "pipeline"))



st.set_page_config(page_title="Custos da Soja — CONAB (IA)", layout="wide")



CORES_GRUPO = {

    "Defensivos": "#a33b32",

    "Fertilizantes": "#5a7247",

    "Sementes": "#b8923f",

    "Terra e outros": "#8a6f5f",

    "Mecanizacao": "#4e6a7d",

    "Custos financeiros e seguros": "#9a8468",

    "Pos-colheita": "#6b8578",

    "Mao de obra": "#7d6b8a",

}

ESCALA_MAPA = [[0, "#e8e4d8"], [1, "#4a5d43"]]

LAYOUT = dict(

    paper_bgcolor="rgba(0,0,0,0)",

    plot_bgcolor="rgba(0,0,0,0)",

    font=dict(family="Arial, sans-serif", size=12, color="#2b2b28"),

    margin=dict(l=55, r=15, t=15, b=45),

    xaxis=dict(gridcolor="#ececE6", zeroline=False),

    yaxis=dict(gridcolor="#ececE6", zeroline=False),

)





@st.cache_data(ttl=600)

def carrega_gold():

    """Le a Gold. Tenta Postgres; se indisponivel, usa o Parquet no repo."""

    try:

        from db import get_engine

        engine = get_engine()

        fato = pd.read_sql("SELECT * FROM gold.fato_custo", engine)

        dim = pd.read_sql(

            "SELECT estado, nome_estado, regiao, geometria FROM gold.dim_estado", engine

        )

        return fato, dim, "postgres"

    except Exception:

        base = Path(__file__).resolve().parent.parent / "dados"

        fato = pd.read_parquet(base / "gold_fato_custo.parquet")

        geo = json.loads((base / "geo" / "br_estados.geojson").read_text(encoding="utf-8"))

        dim = pd.DataFrame([

            {

                "estado": f["properties"]["estado"],

                "nome_estado": f["properties"]["nome_estado"],

                "regiao": f["properties"]["regiao"],

                "geometria": json.dumps(f["geometry"]),

            }

            for f in geo["features"]

        ])

        return fato, dim, "parquet"





@st.cache_data(ttl=600)

def monta_geojson(dim: pd.DataFrame):

    features = []

    for _, r in dim.iterrows():

        features.append({

            "type": "Feature",

            "id": r["estado"],

            "properties": {"estado": r["estado"]},

            "geometry": json.loads(r["geometria"]),

        })

    return {"type": "FeatureCollection", "features": features}





@st.cache_data(ttl=600)

def centroides(dim: pd.DataFrame):

    """Centroide (lon, lat) de cada estado, para posicionar as siglas no mapa."""

    out = {}

    for _, r in dim.iterrows():

        coords = []



        def walk(x):

            if isinstance(x[0], (int, float)):

                coords.append(x)

            else:

                for i in x:

                    walk(i)



        walk(json.loads(r["geometria"])["coordinates"])

        lons = [c[0] for c in coords]

        lats = [c[1] for c in coords]

        out[r["estado"]] = (sum(lons) / len(lons), sum(lats) / len(lats))

    return out





try:

    fato, dim, fonte = carrega_gold()

except Exception as e:

    st.error(

        "Nao consegui carregar os dados. Verifique se o banco esta no ar "

        "(docker compose up -d) e se a Gold foi construida (notebook 04).\n\n"

        f"Detalhe: {e}"

    )

    st.stop()



geojson = monta_geojson(dim)

GRUPOS = sorted(fato["grupo_economico"].unique())



st.sidebar.title("Filtros")



estados = st.sidebar.multiselect(

    "Estado", sorted(fato["estado"].unique()), default=sorted(fato["estado"].unique())

)

a_min, a_max = int(fato["ano"].min()), int(fato["ano"].max())

faixa = st.sidebar.slider("Periodo", a_min, a_max, (a_min, a_max))

grupos_sel = st.sidebar.multiselect("Grupo economico", GRUPOS, default=GRUPOS)

cultivos = st.sidebar.multiselect(

    "Tipo de cultivo", sorted(fato["tipo_cultivo"].unique()),

    default=sorted(fato["tipo_cultivo"].unique()),

)



st.sidebar.caption(

    f"Fonte: {fonte}. Valores nominais (sem correcao pela inflacao). "

    "Custos ausentes contam como zero."

)



d = fato[

    fato["estado"].isin(estados)

    & fato["ano"].between(*faixa)

    & fato["grupo_economico"].isin(grupos_sel)

    & fato["tipo_cultivo"].isin(cultivos)

].copy()



st.title("Custos de Producao da Soja")

st.caption("Serie historica da CONAB — custos por hectare, composicao e produtividade")



if d.empty:

    st.warning("Nenhum dado para os filtros selecionados.")

    st.stop()



GRAO = ["estado", "local", "ano", "tipo_cultivo"]





def custo_por_registro(df):

    """Custo total/ha por registro = soma dos itens (estado-local-ano-cultivo)."""

    return df.groupby(GRAO)["custo_ha"].sum().reset_index(name="custo_total_ha")





def saca_por_registro(df):

    """Custo total/saca por registro = soma dos itens do registro."""

    return df.groupby(GRAO)["custo_60kg"].sum().reset_index(name="custo_total_saca")





def custo_por_kg(df):

    """Custo por kg de soja = custo total/ha do registro / produtividade do registro."""

    r = df.groupby(GRAO).agg(

        custo_total_ha=("custo_ha", "sum"),

        produtiv=("produtividade_kg_ha", "first"),

    ).reset_index()

    r = r[r["produtiv"] > 0].copy()

    r["custo_por_kg"] = r["custo_total_ha"] / r["produtiv"]

    return r





def resumo_interpretativo(d, reg, reg_kg, dim):

    """Monta um paragrafo interpretativo dos dados filtrados (didatico, por regras)."""

    partes = []



    custo_ha = reg["custo_total_ha"].mean()

    custo_kg = reg_kg["custo_por_kg"].mean() if not reg_kg.empty else 0

    partes.append(

        f"No recorte selecionado, produzir soja custa em media "

        f"**R\\\\$ {custo_ha:,.0f} por hectare** — ou cerca de **R\\\\$ {custo_kg:.2f} por quilo** "

        f"de grao. O custo por quilo e a medida mais justa de eficiencia: ele considera "

        f"nao so o quanto se gastou, mas o quanto se colheu."

    )



    gmed = d.groupby("grupo_economico")["custo_ha"].mean().sort_values(ascending=False)

    if len(gmed) > 0 and gmed.sum() > 0:

        top = gmed.index[0]

        peso = gmed.iloc[0] / gmed.sum() * 100

        partes.append(

            f"O maior peso do custo esta em **{top}**, que sozinho responde por cerca de "

            f"**{peso:.0f}%** do total. Isso indica onde o produtor mais gasta e, portanto, "

            f"onde uma variacao de preco tem mais impacto no bolso."

        )



    est = reg.groupby("estado")["custo_total_ha"].mean().sort_values()

    if len(est) > 1:

        caro = dim.loc[dim["estado"] == est.index[-1], "nome_estado"].iloc[0]

        barato = dim.loc[dim["estado"] == est.index[0], "nome_estado"].iloc[0]

        partes.append(

            f"Entre os estados, **{caro}** aparece como o mais caro e **{barato}** como o "

            f"mais barato para produzir. Diferencas assim costumam refletir logistica, "

            f"clima e o quao consolidada e a producao na regiao."

        )



    pa = reg.groupby("ano")["custo_total_ha"].mean()

    anos = sorted(pa.index)

    if len(anos) > 1 and pa[anos[0]] > 0:

        cagr = ((pa[anos[-1]] / pa[anos[0]]) ** (1 / (anos[-1] - anos[0])) - 1) * 100

        partes.append(

            f"Ao longo do periodo ({anos[0]}–{anos[-1]}), o custo cresceu cerca de "

            f"**{cagr:.1f}% ao ano** de forma composta. Atencao: esses valores sao nominais "

            f"— parte dessa alta e apenas a inflacao corroendo o valor do dinheiro, nao "

            f"necessariamente o custo real subindo (a correcao pela inflacao entra em etapa futura)."

        )



    return "\n\n".join(partes)





def coleta_fatos(d, reg, reg_kg, dim):

    """Extrai os numeros-chave dos dados filtrados. Sao ESTES numeros que o

    modelo recebe — ele nao calcula nada, so redige a partir deles."""

    gmed = d.groupby("grupo_economico")["custo_ha"].mean().sort_values(ascending=False)

    est = reg.groupby("estado")["custo_total_ha"].mean().sort_values()

    pa = reg.groupby("ano")["custo_total_ha"].mean()

    anos = sorted(pa.index)



    fatos = {

        "custo_medio_ha": round(reg["custo_total_ha"].mean(), 2),

        "custo_medio_kg": round(reg_kg["custo_por_kg"].mean(), 2) if not reg_kg.empty else None,

        "produtividade_media_kg_ha": round(d["produtividade_kg_ha"].mean(), 0),

        "grupo_maior_peso": gmed.index[0] if len(gmed) else None,

        "grupo_maior_peso_pct": round(gmed.iloc[0] / gmed.sum() * 100, 1) if len(gmed) and gmed.sum() else None,

        "estado_mais_caro": dim.loc[dim["estado"] == est.index[-1], "nome_estado"].iloc[0] if len(est) > 1 else None,

        "estado_mais_barato": dim.loc[dim["estado"] == est.index[0], "nome_estado"].iloc[0] if len(est) > 1 else None,

        "ano_inicial": int(anos[0]) if anos else None,

        "ano_final": int(anos[-1]) if anos else None,

        "n_registros": int(len(d)),

    }

    if len(anos) > 1 and pa[anos[0]] > 0:

        fatos["cagr_pct_ano"] = round(((pa[anos[-1]] / pa[anos[0]]) ** (1 / (anos[-1] - anos[0])) - 1) * 100, 1)

    return fatos





def analise_ia(fatos, modelo="qwen2.5:3b", progress_callback=None):
    """Pede ao Ollama (local) para redigir uma analise a partir dos FATOS ja
    calculados. O modelo recebe os numeros prontos e apenas os interpreta.

    A resposta e recebida em streaming para permitir atualizar a barra de
    carregamento enquanto o modelo esta gerando o texto.

    Retorna (texto, erro).
    """
    prompt = f"""Voce e um analista de dados agricolas. Escreva uma analise CURTA
(3 a 4 frases, tom didatico e acessivel) sobre custos de producao de soja no Brasil.

Use APENAS os numeros fornecidos abaixo. NAO invente, NAO calcule, NAO acrescente
numeros que nao estejam aqui. Se um numero nao foi dado, nao o mencione.

Dados (ja calculados):
{json.dumps(fatos, ensure_ascii=False, indent=2)}

Contexto: valores nominais (nao corrigidos pela inflacao). O custo por quilo mede
eficiencia (considera quanto se gastou e quanto se colheu).

Escreva em portugues, em texto corrido, sem listar os numeros como topicos."""

    try:
        import ollama

        if progress_callback:
            progress_callback(5)

        resposta_stream = ollama.chat(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3},
            stream=True,
        )

        partes = []
        progresso = 10

        for chunk in resposta_stream:
            conteudo = chunk.get("message", {}).get("content", "")
            if conteudo:
                partes.append(conteudo)

            # O Ollama nao informa previamente o total de tokens da resposta.
            # A barra representa atividade/progresso aproximado durante o streaming.
            progresso = min(95, progresso + 2)
            if progress_callback:
                progress_callback(progresso)

        if progress_callback:
            progress_callback(100)

        return "".join(partes).strip(), None

    except ImportError:
        return None, "A biblioteca 'ollama' nao esta instalada. Rode: pip install ollama"
    except Exception as e:
        return None, (
            "Nao consegui falar com o Ollama. Verifique se ele esta rodando e se o "
            f"modelo '{modelo}' foi baixado (ollama pull {modelo}).\n\nDetalhe: {e}"
        )


def monta_contexto_chat(d, reg, reg_saca, reg_kg, dim):
    """Monta um contexto compacto do recorte filtrado para o chat com IA.

    O objetivo e permitir perguntas sobre os mesmos dados que alimentam o dashboard
    sem enviar milhares de linhas para a janela de contexto do modelo.
    """
    fatos = coleta_fatos(d, reg, reg_kg, dim)

    por_ano = (
        reg.groupby("ano")["custo_total_ha"]
        .mean()
        .reset_index()
        .round({"custo_total_ha": 2})
    )

    por_estado = (
        reg.groupby("estado")["custo_total_ha"]
        .mean()
        .reset_index()
        .merge(dim[["estado", "nome_estado"]], on="estado", how="left")
        .sort_values("custo_total_ha", ascending=False)
        .round({"custo_total_ha": 2})
    )

    por_grupo = (
        d.groupby("grupo_economico")["custo_ha"]
        .mean()
        .reset_index()
        .sort_values("custo_ha", ascending=False)
        .round({"custo_ha": 2})
    )

    por_cultivo = (
        reg.groupby("tipo_cultivo")["custo_total_ha"]
        .mean()
        .reset_index()
        .round({"custo_total_ha": 2})
    )

    produtividade_estado = (
        d.groupby("estado")["produtividade_kg_ha"]
        .mean()
        .reset_index()
        .merge(dim[["estado", "nome_estado"]], on="estado", how="left")
        .sort_values("produtividade_kg_ha", ascending=False)
        .round({"produtividade_kg_ha": 0})
    )

    top_categorias = (
        d.groupby(["grupo_economico", "categoria"])["custo_ha"]
        .mean()
        .reset_index()
        .sort_values("custo_ha", ascending=False)
        .head(25)
        .round({"custo_ha": 2})
    )

    top_descricoes = (
        d.groupby(["grupo_economico", "descricao"])["custo_ha"]
        .mean()
        .reset_index()
        .sort_values("custo_ha", ascending=False)
        .head(30)
        .round({"custo_ha": 2})
    )

    contexto = {
        "filtros_do_recorte": {
            "estados": sorted(d["estado"].dropna().astype(str).unique().tolist()),
            "ano_min": int(d["ano"].min()),
            "ano_max": int(d["ano"].max()),
            "grupos_economicos": sorted(
                d["grupo_economico"].dropna().astype(str).unique().tolist()
            ),
            "tipos_cultivo": sorted(
                d["tipo_cultivo"].dropna().astype(str).unique().tolist()
            ),
        },
        "fatos_principais": fatos,
        "custo_medio_ha_por_ano": por_ano.to_dict(orient="records"),
        "custo_medio_ha_por_estado": por_estado[
            ["estado", "nome_estado", "custo_total_ha"]
        ].to_dict(orient="records"),
        "custo_medio_ha_por_grupo": por_grupo.to_dict(orient="records"),
        "custo_medio_ha_por_cultivo": por_cultivo.to_dict(orient="records"),
        "produtividade_media_por_estado": produtividade_estado[
            ["estado", "nome_estado", "produtividade_kg_ha"]
        ].to_dict(orient="records"),
        "categorias_com_maior_custo_medio": top_categorias.to_dict(orient="records"),
        "descricoes_com_maior_custo_medio": top_descricoes.to_dict(orient="records"),
    }

    return contexto


def responde_chat_ia(
    pergunta,
    contexto_dados,
    historico=None,
    modelo="qwen2.5:3b",
    progress_callback=None,
):
    """Responde perguntas sobre o recorte atual do dashboard usando Ollama local."""
    try:
        import ollama

        prompt_sistema = f"""Voce e um analista de dados agricolas especializado em custos
de producao de soja. Responda em portugues usando APENAS o contexto de dados fornecido.

Regras:
- Nao invente numeros nem fatos.
- Nao use conhecimento externo para preencher lacunas do dataset.
- Quando a pergunta exigir informacao que nao esteja no contexto, diga claramente que
  o recorte disponivel nao permite responder com seguranca.
- Os valores sao nominais e nao corrigidos pela inflacao.
- Seja objetivo, mas explique comparacoes e tendencias quando forem relevantes.
- Considere que os dados abaixo representam exatamente o recorte atualmente selecionado
  nos filtros do dashboard.

CONTEXTO DOS DADOS:
{json.dumps(contexto_dados, ensure_ascii=False)}
"""

        mensagens = [{"role": "system", "content": prompt_sistema}]

        if historico:
            for msg in historico[-6:]:
                if msg.get("role") in {"user", "assistant"}:
                    mensagens.append(
                        {"role": msg["role"], "content": str(msg.get("content", ""))}
                    )

        mensagens.append({"role": "user", "content": pergunta})

        if progress_callback:
            progress_callback(5)

        resposta_stream = ollama.chat(
            model=modelo,
            messages=mensagens,
            options={"temperature": 0.2},
            stream=True,
        )

        partes = []
        progresso = 10

        for chunk in resposta_stream:
            conteudo = chunk.get("message", {}).get("content", "")
            if conteudo:
                partes.append(conteudo)

            progresso = min(95, progresso + 2)
            if progress_callback:
                progress_callback(progresso)

        if progress_callback:
            progress_callback(100)

        return "".join(partes).strip(), None

    except ImportError:
        return None, "A biblioteca 'ollama' nao esta instalada. Rode: pip install ollama"
    except Exception as e:
        return None, (
            "Nao consegui falar com o Ollama. Verifique se ele esta rodando e se o "
            f"modelo '{modelo}' foi baixado (ollama pull {modelo}).\n\nDetalhe: {e}"
        )




reg = custo_por_registro(d)

reg_saca = saca_por_registro(d)

reg_kg = custo_por_kg(d)



# KPIs

k1, k2, k3, k4, k5 = st.columns(5)

k1.metric("Custo medio (R$/ha)", f"{reg['custo_total_ha'].mean():,.0f}")

k2.metric("Custo medio (R$/saca)", f"{reg_saca['custo_total_saca'].mean():.2f}")

k3.metric("Custo por kg (R$)", f"{reg_kg['custo_por_kg'].mean():.2f}")

k4.metric("Produtividade (kg/ha)", f"{d['produtividade_kg_ha'].mean():,.0f}")

k5.metric("Registros", f"{len(d):,}")



with st.expander("Leitura dos dados — resumo interpretativo", expanded=True):

    st.markdown(resumo_interpretativo(d, reg, reg_kg, dim))



# --- Analise por IA (Ollama local) ---

with st.expander("Analise com IA (experimental — requer Ollama local)", expanded=False):

    st.caption(

        "Gera uma interpretacao redigida por um modelo de linguagem rodando na sua "

        "maquina (Ollama + Qwen). O modelo recebe os numeros ja calculados e apenas "

        "os redige — nao faz contas. Requer o Ollama instalado e rodando."

    )

    if st.button("Gerar analise com IA"):

        fatos = coleta_fatos(d, reg, reg_kg, dim)

        barra_ia = st.progress(0, text="Preparando analise...")

        def atualiza_progresso_analise(valor):
            barra_ia.progress(valor, text=f"Modelo processando... {valor}%")

        texto, erro = analise_ia(
            fatos,
            progress_callback=atualiza_progresso_analise,
        )

        if erro:

            barra_ia.empty()
            st.warning(erro)

        else:

            barra_ia.progress(100, text="Analise concluida.")
            st.markdown(texto)

        with st.popover("Ver os numeros enviados ao modelo"):

            st.json(fatos)



st.divider()



CENTROIDES = centroides(dim)



aba1, aba2, aba3, aba4, aba5, aba6, aba7 = st.tabs(

    ["Evolucao", "Composicao", "Geografia", "Produtividade", "Cultivos", "Dados", "Chat IA"]

)



# === ABA 1 — EVOLUCAO ===

with aba1:

    evo = reg.groupby("ano")["custo_total_ha"].mean().reset_index()

    fig = px.line(evo, x="ano", y="custo_total_ha", markers=True)

    fig.update_traces(line_color="#4a5d43")

    fig.update_layout(**LAYOUT, height=340, yaxis_title="R$/ha", xaxis_title="Ano")

    st.subheader("Custo total por hectare ao longo do tempo")

    st.plotly_chart(fig, use_container_width=True)

    st.caption(

        "Como ler: cada ponto e o custo medio de um ano. Uma linha que sobe indica "

        "custo crescente — mas lembre que sao valores nominais, entao parte da subida "

        "e inflacao. Observe a inclinacao: quanto mais ingreme, mais rapido o custo mudou."

    )



    pa = reg.groupby("ano")["custo_total_ha"].mean()

    anos_ord = sorted(pa.index)

    if len(anos_ord) > 1:

        v0, v1 = pa[anos_ord[0]], pa[anos_ord[-1]]

        n = anos_ord[-1] - anos_ord[0]

        cagr = ((v1 / v0) ** (1 / n) - 1) * 100 if v0 > 0 and n > 0 else 0

        total = (v1 / v0 - 1) * 100 if v0 > 0 else 0

        cc1, cc2, cc3 = st.columns(3)

        cc1.metric("CAGR do custo/ha", f"{cagr:.1f}% ao ano")

        cc2.metric(f"Variacao total {anos_ord[0]}-{anos_ord[-1]}", f"{total:.0f}%")

        cc3.metric("Anos no periodo", f"{n}")

        st.caption("CAGR = crescimento composto ao ano. Valores nominais — parte da "

                   "alta e inflacao (deflacao entra em etapa futura).")



    comp = d.groupby(["ano", "grupo_economico"])["custo_ha"].mean().reset_index()

    fig2 = px.line(comp, x="ano", y="custo_ha", color="grupo_economico",

                   color_discrete_map=CORES_GRUPO)

    fig2.update_layout(**LAYOUT, height=360, yaxis_title="R$/ha", xaxis_title="Ano",

                       legend=dict(font=dict(size=10), orientation="h", y=-0.25))

    st.subheader("Evolucao por grupo economico")

    st.plotly_chart(fig2, use_container_width=True)

    st.caption(

        "Como ler: cada linha e um grupo de custo (fertilizante, defensivo, etc.). "

        "Linhas que se descolam para cima ao longo do tempo sao os grupos que mais "

        "encareceram. Compare a distancia entre as linhas para ver quais custos pesam mais."

    )



# === ABA 2 — COMPOSICAO ===

with aba2:

    c1, c2 = st.columns(2)

    grupo_med = d.groupby("grupo_economico")["custo_ha"].mean().reset_index()



    with c1:

        st.subheader("Participacao por grupo")

        fig3 = px.pie(grupo_med, names="grupo_economico", values="custo_ha",

                      color="grupo_economico", color_discrete_map=CORES_GRUPO, hole=0.45)

        fig3.update_traces(textinfo="percent", textfont_size=11)

        fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)",

                           font=dict(family="Arial, sans-serif", color="#2b2b28"),

                           margin=dict(l=10, r=10, t=10, b=10), height=330,

                           legend=dict(font=dict(size=10)))

        st.plotly_chart(fig3, use_container_width=True)

        st.caption(

            "Como ler: cada fatia e a parcela de um grupo no custo total. Fatias maiores "

            "sao os custos que mais pesam. Ideal para ver, num relance, onde vai o dinheiro."

        )



    with c2:

        st.subheader("Custo medio por grupo")

        gm = grupo_med.sort_values("custo_ha")

        fig4 = px.bar(gm, x="custo_ha", y="grupo_economico", orientation="h",

                      color="grupo_economico", color_discrete_map=CORES_GRUPO)

        fig4.update_layout(**LAYOUT, height=330, showlegend=False,

                           xaxis_title="R$/ha", yaxis_title="")

        st.plotly_chart(fig4, use_container_width=True)

        st.caption(

            "Como ler: as barras ordenam os grupos do menor ao maior custo. "

            "A barra mais longa e o grupo que mais consome recursos por hectare."

        )



    st.subheader("Composicao ao longo do tempo (participacao %)")

    comp_pct = d.groupby(["ano", "grupo_economico"])["custo_ha"].mean().reset_index()

    tot = comp_pct.groupby("ano")["custo_ha"].transform("sum")

    comp_pct["pct"] = comp_pct["custo_ha"] / tot * 100

    fig5 = px.area(comp_pct, x="ano", y="pct", color="grupo_economico",

                   color_discrete_map=CORES_GRUPO)

    fig5.update_layout(**LAYOUT, height=360, yaxis_title="% do custo", xaxis_title="Ano",

                       legend=dict(font=dict(size=10), orientation="h", y=-0.25))

    st.plotly_chart(fig5, use_container_width=True)

    st.caption(

        "Como ler: aqui o total de cada ano vira 100%, e cada faixa mostra a fatia de um "

        "grupo. Diferente do grafico de valores, este revela se um custo ganhou ou perdeu "

        "importancia relativa ao longo do tempo, mesmo que todos tenham subido em reais."

    )



    st.subheader("Custo medio por grupo empilhado, por ano")

    emp_ano = d.groupby(["ano", "grupo_economico"])["custo_ha"].mean().reset_index()

    fig_ea = px.bar(emp_ano, x="ano", y="custo_ha", color="grupo_economico",

                    color_discrete_map=CORES_GRUPO)

    fig_ea.update_layout(**LAYOUT, height=380, barmode="stack",

                         yaxis_title="R$/ha", xaxis_title="Ano",

                         legend=dict(font=dict(size=10), orientation="h", y=-0.25))

    st.plotly_chart(fig_ea, use_container_width=True)



    st.subheader("Custo medio por grupo empilhado, por estado")

    emp_est = (

        d.groupby(["estado", "grupo_economico"])["custo_ha"].mean().reset_index()

        .merge(dim[["estado", "nome_estado"]], on="estado")

    )

    total_est = emp_est.groupby("nome_estado")["custo_ha"].sum().sort_values(ascending=False)

    ordem = total_est.index.tolist()

    fig_ee = px.bar(emp_est, x="nome_estado", y="custo_ha", color="grupo_economico",

                    color_discrete_map=CORES_GRUPO,

                    category_orders={"nome_estado": ordem})

    fig_ee.update_layout(**LAYOUT, height=400, barmode="stack",

                         yaxis_title="R$/ha", xaxis_title="",

                         legend=dict(font=dict(size=10), orientation="h", y=-0.3))

    st.plotly_chart(fig_ee, use_container_width=True)

    st.caption(

        "Como ler: cada barra e um estado, dividida pelos grupos de custo empilhados. "

        "A altura total e o custo do estado; os blocos mostram quanto cada grupo contribui. "

        "Compare a mesma cor entre estados para ver onde um grupo pesa mais."

    )



# === ABA 3 — GEOGRAFIA ===

with aba3:

    metrica = st.radio("Metrica",

                       ["Custo (R$/ha)", "Custo (R$/saca)", "Produtividade (kg/ha)"],

                       horizontal=True)

    if metrica == "Custo (R$/ha)":

        mapa_df = reg.groupby("estado")["custo_total_ha"].mean().reset_index()

        col, label = "custo_total_ha", "R$/ha"

    elif metrica == "Custo (R$/saca)":

        mapa_df = reg_saca.groupby("estado")["custo_total_saca"].mean().reset_index()

        col, label = "custo_total_saca", "R$/saca"

    else:

        mapa_df = d.groupby("estado")["produtividade_kg_ha"].mean().reset_index()

        col, label = "produtividade_kg_ha", "kg/ha"



    m1, m2 = st.columns(2)

    with m1:

        ests_mapa = mapa_df["estado"].tolist()

        fig6 = go.Figure()

        fig6.add_trace(go.Choropleth(

            geojson=geojson, locations=mapa_df["estado"], z=mapa_df[col],

            featureidkey="properties.estado", colorscale=ESCALA_MAPA,

            marker_line_color="white", marker_line_width=0.8,

            colorbar=dict(title=label, thickness=12, len=0.7),

            hovertext=mapa_df["estado"], hovertemplate="%{hovertext}: %{z:.0f}<extra></extra>",

        ))

        fig6.add_trace(go.Scattergeo(

            lon=[CENTROIDES[e][0] for e in ests_mapa],

            lat=[CENTROIDES[e][1] for e in ests_mapa],

            text=ests_mapa, mode="text",

            textfont=dict(size=11, color="#2b2b28", family="Arial"),

            showlegend=False, hoverinfo="skip",

        ))

        fig6.update_geos(fitbounds="locations", visible=False,

                         bgcolor="rgba(0,0,0,0)", showland=True, landcolor="#f5f4f0",

                         showlakes=False, resolution=50)

        fig6.update_layout(height=460, margin=dict(l=0, r=0, t=0, b=0),

                           paper_bgcolor="rgba(0,0,0,0)")

        st.plotly_chart(fig6, use_container_width=True)

        st.caption("Mapa por estado com siglas. Nivel municipal quando o de-para de nomes for resolvido.")

        st.caption(

            "Como ler: quanto mais escuro o estado, maior o valor da metrica escolhida acima. "

            "Compare estados vizinhos e regioes para identificar onde produzir e mais caro ou "

            "mais eficiente."

        )



    with m2:

        st.subheader("Ranking por estado")

        rank = mapa_df.merge(dim[["estado", "nome_estado"]], on="estado").sort_values(col)

        fig7 = px.bar(rank, x=col, y="nome_estado", orientation="h", text=col)

        fig7.update_traces(marker_color="#7d6b52", texttemplate="%{text:.0f}",

                           textposition="auto", textfont_size=10)

        fig7.update_layout(**LAYOUT, height=430, xaxis_title=label, yaxis_title="")

        st.plotly_chart(fig7, use_container_width=True)



# === ABA 4 — PRODUTIVIDADE ===

with aba4:

    st.subheader("Produtividade versus custo por saca")

    st.caption("Cada ponto e um municipio/ano. Mais eficiente: canto inferior direito.")



    scat = (

        d.groupby(["estado", "local", "ano"])

        .agg(produtividade=("produtividade_kg_ha", "mean"),

             custo_saca=("custo_60kg", "sum"))

        .reset_index()

    )

    fig8 = px.scatter(scat, x="produtividade", y="custo_saca", color="estado",

                      hover_data=["local", "ano"])

    fig8.update_traces(marker=dict(size=8, opacity=0.65))

    fig8.update_layout(**LAYOUT, height=430,

                       xaxis_title="Produtividade (kg/ha)", yaxis_title="Custo (R$/saca)")

    st.plotly_chart(fig8, use_container_width=True)

    st.caption(

        "Como ler: o eixo horizontal e a produtividade (quanto se colheu) e o vertical e "

        "o custo por saca (quanto custou cada saca). O ponto ideal fica embaixo e a direita: "

        "muita colheita com baixo custo. Pontos no alto a esquerda sao os menos eficientes — "

        "pouca colheita e custo alto por saca."

    )



    st.subheader("Indicadores por estado")

    tab = (

        reg.groupby("estado")["custo_total_ha"].mean().reset_index(name="Custo R$/ha")

        .merge(reg_saca.groupby("estado")["custo_total_saca"].mean().reset_index(name="Custo R$/saca"), on="estado")

        .merge(reg_kg.groupby("estado")["custo_por_kg"].mean().reset_index(name="Custo R$/kg"), on="estado")

        .merge(d.groupby("estado")["produtividade_kg_ha"].mean().reset_index(name="Produtividade kg/ha"), on="estado")

        .merge(dim[["estado", "nome_estado"]], on="estado")

    )

    tab = tab[["nome_estado", "Custo R$/ha", "Custo R$/saca", "Custo R$/kg", "Produtividade kg/ha"]]

    tab.columns = ["Estado", "Custo R$/ha", "Custo R$/saca", "Custo R$/kg", "Produtividade kg/ha"]

    tab = tab.sort_values("Custo R$/ha", ascending=False)

    st.dataframe(

        tab.style.format({"Custo R$/ha": "{:,.0f}", "Custo R$/saca": "{:.2f}",

                          "Custo R$/kg": "{:.2f}", "Produtividade kg/ha": "{:,.0f}"}),

        use_container_width=True, hide_index=True,

    )



# === ABA 5 — CULTIVOS (convencional vs transgenico) ===

with aba5:

    st.subheader("Convencional vs. transgenico")

    st.caption(

        "Comparacao justa apenas onde os dois cultivos existem no mesmo estado e ano. "

        "Comparar locais/anos diferentes nao seria valido."

    )



    piv = (

        reg.groupby(["estado", "ano", "tipo_cultivo"])["custo_total_ha"]

        .mean().reset_index()

    )

    n_tipos = piv.groupby(["estado", "ano"])["tipo_cultivo"].transform("nunique")

    comp = piv[n_tipos > 1].copy()



    if comp.empty:

        st.info("Nenhum par comparavel (estado-ano com ambos os cultivos) no recorte atual.")

    else:

        largo = comp.pivot_table(

            index=["estado", "ano"], columns="tipo_cultivo", values="custo_total_ha"

        ).reset_index()

        largo["diferenca_%"] = (

            (largo["transgenico"] - largo["convencional"]) / largo["convencional"] * 100

        )



        media_conv = largo["convencional"].mean()

        media_ogm = largo["transgenico"].mean()

        cA, cB, cC = st.columns(3)

        cA.metric("Custo medio convencional (R$/ha)", f"{media_conv:,.0f}")

        cB.metric("Custo medio transgenico (R$/ha)", f"{media_ogm:,.0f}")

        cC.metric("Diferenca media", f"{(media_ogm/media_conv-1)*100:+.1f}%")



        st.markdown("**Custo/ha por ano — convencional vs. transgenico**")

        fig_c = px.bar(

            comp, x="ano", y="custo_total_ha", color="tipo_cultivo", barmode="group",

            color_discrete_map={"convencional": "#5a7247", "transgenico": "#8a6f5f"},

            labels={"custo_total_ha": "R$/ha", "tipo_cultivo": "Cultivo"},

        )

        fig_c.update_layout(**LAYOUT, height=380,

                            legend=dict(font=dict(size=10), orientation="h", y=-0.25))

        st.plotly_chart(fig_c, use_container_width=True)

        st.caption(

            "Como ler: para cada ano, as barras lado a lado mostram o custo do convencional "

            "e do transgenico. Barras de altura parecida indicam que o tipo de semente pouco "

            "muda o custo total; diferencas grandes apontam onde um compensa mais que o outro."

        )



        st.markdown("**Diferenca do transgenico sobre o convencional (%)**")

        st.caption("Positivo: transgenico mais caro. Negativo: transgenico mais barato.")

        largo_show = largo.merge(dim[["estado", "nome_estado"]], on="estado")

        largo_show = largo_show[["nome_estado", "ano", "convencional", "transgenico", "diferenca_%"]]

        largo_show.columns = ["Estado", "Ano", "Convencional R$/ha", "Transgenico R$/ha", "Diferenca %"]

        st.dataframe(

            largo_show.sort_values(["Estado", "Ano"]).style.format({

                "Convencional R$/ha": "{:,.0f}", "Transgenico R$/ha": "{:,.0f}",

                "Diferenca %": "{:+.1f}",

            }),

            use_container_width=True, hide_index=True,

        )



# === ABA 6 — DADOS ===

with aba6:

    st.subheader("Dados detalhados")

    st.caption(

        "Tabela corrida (fato + localidade), sem agregacao, aplicando os filtros "

        "da barra lateral. Use o botao para baixar em CSV."

    )



    tabela = (

        d.merge(dim[["estado", "nome_estado", "regiao"]], on="estado")

        [["estado", "nome_estado", "regiao", "local", "ano", "tipo_cultivo",

          "grupo_economico", "categoria", "descricao", "custo_ha", "custo_60kg",

          "produtividade_kg_ha"]]

        .sort_values(["estado", "local", "ano"])

        .reset_index(drop=True)

    )



    st.download_button(

        "Baixar CSV",

        data=tabela.to_csv(index=False).encode("utf-8-sig"),

        file_name="custos_soja_filtrado.csv",

        mime="text/csv",

    )



    st.dataframe(tabela, use_container_width=True, hide_index=True, height=500)

    st.caption(f"{len(tabela):,} linhas no recorte atual.")

# === ABA 7 — CHAT IA ===

with aba7:

    st.subheader("Chat com os dados")

    st.caption(
        "Faca perguntas sobre o mesmo recorte de dados selecionado nos filtros do dashboard. "
        "O modelo roda localmente via Ollama e recebe agregacoes do dataset atual para responder."
    )

    if "chat_soja_mensagens" not in st.session_state:
        st.session_state.chat_soja_mensagens = []

    topo_chat_1, topo_chat_2 = st.columns([5, 1])

    with topo_chat_2:
        if st.button("Limpar chat", key="limpar_chat_soja"):
            st.session_state.chat_soja_mensagens = []
            st.rerun()

    for mensagem in st.session_state.chat_soja_mensagens:
        with st.chat_message(mensagem["role"]):
            st.markdown(mensagem["content"])

    pergunta = st.chat_input(
        "Pergunte algo sobre os custos de producao da soja...",
        key="chat_soja_input",
    )

    if pergunta:
        st.session_state.chat_soja_mensagens.append(
            {"role": "user", "content": pergunta}
        )

        with st.chat_message("user"):
            st.markdown(pergunta)

        contexto_chat = monta_contexto_chat(d, reg, reg_saca, reg_kg, dim)

        with st.chat_message("assistant"):
            barra_chat = st.progress(0, text="Preparando os dados para o modelo...")

            def atualiza_progresso_chat(valor):
                barra_chat.progress(valor, text=f"Modelo analisando os dados... {valor}%")

            resposta_chat, erro_chat = responde_chat_ia(
                pergunta=pergunta,
                contexto_dados=contexto_chat,
                historico=st.session_state.chat_soja_mensagens[:-1],
                progress_callback=atualiza_progresso_chat,
            )

            if erro_chat:
                barra_chat.empty()
                st.warning(erro_chat)
            else:
                barra_chat.progress(100, text="Resposta concluida.")
                st.markdown(resposta_chat)
                st.session_state.chat_soja_mensagens.append(
                    {"role": "assistant", "content": resposta_chat}
                )


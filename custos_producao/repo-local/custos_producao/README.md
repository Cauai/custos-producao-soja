# Custos de Produção — Soja (CONAB)

Análise da série histórica de custos de produção da soja (1997–2026), da CONAB,
sobre um banco **PostgreSQL** em **arquitetura medalhão** (bronze / silver / gold).

O projeto é portátil: você versiona o **código**, não o banco. Cada PC reconstrói
o banco rodando o pipeline.

## Arquitetura

    data/raw/dados_custos_soja.xls
            │  01_bronze_ingest.py
            ▼   schema BRONZE   (reflexo fiel do arquivo)
            │  02_silver_parse.py
            ▼   schema SILVER   (parseado, normalizado)
            │  03_gold_build.py
            ▼   schema GOLD     (consumo — a definir)
            ▼   dashboard/app.py (Streamlit)

## Subir o banco (em cada PC)

    cp .env.example .env        # ajuste a senha (idêntico nos dois PCs)
    docker compose up -d        # sobe o Postgres e cria os 3 schemas
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python pipeline/db.py       # deve listar bronze, gold, silver

## Trabalhar nos dois PCs

Cada PC roda seu próprio Postgres local. O Git sincroniza o código; o pipeline
reconstrói o banco. Como o pipeline é idempotente e o .xls é pequeno, reconstruir
leva segundos — não é preciso sincronizar bancos manualmente.

## Estado atual

- [x] Fundação: Docker + Postgres + schemas
- [ ] Bronze — ingestão das 515 abas
- [ ] Silver — parsing por âncora (3 eras de layout)
- [ ] Gold — modelagem de consumo
- [ ] Dashboard Streamlit
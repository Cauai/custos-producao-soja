-- ============================================================================
-- Inicialização do banco — arquitetura medalhão em schemas
-- Roda automaticamente na primeira subida do container (initdb).
-- Um banco só (custos_soja), três camadas isoladas por schema.
-- ============================================================================

-- BRONZE: dados fiéis do .xls, sem interpretação. Uma verdade bruta, rastreável.
CREATE SCHEMA IF NOT EXISTS bronze;

-- SILVER: dados parseados, limpos e normalizados (formato longo).
CREATE SCHEMA IF NOT EXISTS silver;

-- GOLD: camada de consumo (modelagem definida mais adiante — placeholder por ora).
CREATE SCHEMA IF NOT EXISTS gold;

COMMENT ON SCHEMA bronze IS 'Camada bruta: reflexo fiel do arquivo de origem, sem transformação.';
COMMENT ON SCHEMA silver IS 'Camada tratada: parseada, normalizada, formato longo.';
COMMENT ON SCHEMA gold   IS 'Camada de consumo: modelagem a definir (dashboard/BI).';
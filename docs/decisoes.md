# Decisões de arquitetura (ADRs)

---

## ADR-001 — Contratos de SLO em YAML, versionados no repositório

**Contexto.** Limiares poderiam viver no banco, num painel de configuração ou
no código Python.

**Decisão.** Um arquivo YAML por dataset, em `contracts/`, com `dataset`,
`tabela`, `dono` e limiares.

**Consequências.**

- (+) SLO vira acordo revisável em PR, com histórico no Git
- (+) `dono` explícito: todo dado tem alguém responsável
- (+) Fácil validar no CI (o parser falha com mensagem clara)
- (−) Exige disciplina de manter contrato e modelo em sincronia

---

## ADR-002 — Baseline sazonal com mediana e MAD

**Contexto.** Comparar o volume de hoje com a média dos últimos dias gera
alerta falso todo fim de semana (vende menos) e perde queda real depois de um
pico (a média sobe).

**Decisão.** Comparar com o **mesmo dia da semana** das últimas 4 semanas e usar
**mediana + MAD** (desvio absoluto mediano) como medida de dispersão.

**Consequências.**

- (+) Sazonalidade semanal deixa de gerar incidente
- (+) Um outlier (Black Friday) não contamina a base
- (+) Independe de biblioteca de ML
- (−) Precisa de pelo menos algumas semanas de histórico; no primeiro dia o
  check retorna OK com aviso explícito

---

## ADR-003 — Deduplicação por fingerprint + índice único parcial

**Contexto.** Um pipeline quebrado falha a cada execução. Sem deduplicação, são
dezenas de incidentes iguais — e o time para de olhar o painel.

**Decisão.** `fingerprint = dataset:check`. Um índice único parcial no Postgres
(`where status = 'aberto'`) garante **no banco** no máximo um incidente aberto
por fingerprint. Enquanto falha, o existente é atualizado; quando volta, é
resolvido automaticamente.

**Consequências.**

- (+) Garantia no nível do banco, não só na aplicação
- (+) MTTR calculado sem intervenção manual
- (−) Dois problemas diferentes no mesmo `dataset:check` viram o mesmo
  incidente — aceitável, mas exige consciência

---

## ADR-004 — Lineage a partir do manifest do dbt

**Contexto.** As opções eram OpenLineage + Marquez (padrão de mercado,
infraestrutura extra) ou ler o `manifest.json` que o dbt já gera.

**Decisão.** Ler o manifest e construir o grafo de dependências em memória.

**Consequências.**

- (+) Zero infraestrutura adicional; funciona no `docker compose up`
- (+) Cobre o caso real deste projeto (lineage dentro do dbt)
- (−) Não vê lineage de fora do dbt (Airflow, jobs manuais, BI)
- (−) Depende do manifest estar atualizado — documentado no README

Promover para OpenLineage é o primeiro item do roadmap, justamente para cobrir
lineage entre sistemas.

---

## ADR-005 — Só `ERROR` abre incidente

**Contexto.** `WARN` poderia abrir incidente de severidade baixa.

**Decisão.** `WARN` aparece no painel e no histórico, mas não abre incidente.
Incidente é reservado para violação de contrato (`ERROR`).

**Consequências.**

- (+) Menos ruído; "incidente aberto" passa a significar algo
- (+) Severidade fica reservada para o alcance, não para degradação leve
- (−) Degradação pode passar despercebida se ninguém olhar o painel — mitigado
  pela métrica de "verificações saudáveis" na visão geral

---

## ADR-006 — Métricas em Postgres, não Prometheus

**Contexto.** Prometheus/Grafana é o padrão para métricas operacionais.

**Decisão.** Guardar resultados e incidentes no próprio Postgres.

**Consequências.**

- (+) Uma dependência a menos; consultas SQL livres para o dashboard
- (+) Fácil correlacionar com os dados de negócio
- (−) Sem retenção/agregação automática; para alto volume, exportar para
  Prometheus (roadmap)

---

## ADR-007 — Simulador de falhas dentro do repositório

**Contexto.** Projetos de confiabilidade normalmente mostram o "caminho feliz".

**Decisão.** Incluir `simulator/falhas.py`, que injeta incidentes reais e permite
demonstrar detecção e MTTR em segundos.

**Consequências.**

- (+) O valor do projeto é demonstrável, não afirmado
- (+) Serve como teste de fumaça do próprio Sentinela
- (−) Código extra que não é "produto" — aceitável em projeto de portfólio

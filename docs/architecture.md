# Architecture

_Synthetic data - fictional lender Vittora Credit._

## 1. System overview

```mermaid
flowchart LR
    subgraph SRC["Source systems (simulated)"]
        CRM[CRM<br/>customers]
        LOS[Loan origination<br/>applications]
        LMS[Loan management<br/>loans, repayments]
        PAY[Payment gateway<br/>transactions]
        EVT[Mixpanel export<br/>product_events]
        HD[Helpdesk<br/>support_tickets]
        EXP[Experimentation<br/>experiments, assignments]
        MKT[Marketing<br/>campaigns]
    end
    SRC -->|CSV / CSV.gz| RAW[(data/raw)]
    RAW --> EX[Extract<br/>lineage: md5, rows]
    EX --> V1{{DQ checks<br/>raw layer}}
    V1 --> TR[Transform<br/>type, dedupe, repair,<br/>quarantine, log]
    TR --> V2{{DQ gate<br/>curated layer}}
    V2 -->|critical = 0| PQ[(data/processed<br/>Parquet)]
    V2 -.->|critical > 0| STOP[Stop + alert]
    TR --> Q[(data/quarantine)]
    PQ --> WH[(DuckDB warehouse<br/>core: PK/FK enforced)]
    WH --> MARTS[(marts: funnel, loan performance,<br/>portfolio snapshots, revenue ledger,<br/>customer 360, daily metrics)]
    MARTS --> SQL[SQL analytics<br/>50 queries]
    MARTS --> KPI[KPI layer<br/>28 governed KPIs]
    MARTS --> AN[Anomaly detection]
    MARTS --> AB[Experiment analysis]
    MARTS --> SEG[Segmentation]
    SQL & KPI & AN & AB & SEG --> FACTS[Fact sheet<br/>numbered, sourced]
    FACTS --> AI[AI analyst<br/>Claude + grounding check]
    AI --> SUM[Weekly executive summary]
    MARTS --> PBI[Power BI extract<br/>star schema CSV]
    PBI --> REPORT[8-page Power BI report]
    SQL & KPI & AB & SEG --> CHARTS[Charts / docs]
```

## 2. Layers

| Layer | Storage | Produced by | Contract |
|---|---|---|---|
| Raw | `data/raw/*.csv(.gz)` | source systems (`python/generate_data.py`) | as delivered - may contain defects |
| Curated | `data/processed/*.parquet` | `etl/transform.py` | `data_quality/contracts.yaml`, zero critical failures |
| Quarantine | `data/quarantine/*_quarantine.csv` | `etl/transform.py` | rows that cannot be repaired, with a reason |
| Core | DuckDB `core.*` | `etl/load.py` + `sql/ddl/01_core_schema.sql` | PK/FK/CHECK constraints enforced at load |
| Marts | DuckDB `marts.*` | `sql/marts/*.sql` | business definitions in one place |
| Serving | `outputs/`, `powerbi/data/`, `docs/images/` | analytics modules | consumed by people, Power BI and the AI layer |

## 3. Data model (core)

```mermaid
erDiagram
    PRODUCTS ||--o{ APPLICATIONS : product_id
    PRODUCTS ||--o{ LOANS : product_id
    PRODUCTS ||--o{ MARKETING_CAMPAIGNS : target_product_id
    MARKETING_CAMPAIGNS ||--o{ CUSTOMERS : campaign_id
    CUSTOMERS ||--o{ APPLICATIONS : customer_id
    CUSTOMERS ||--o{ LOANS : customer_id
    CUSTOMERS ||--o{ REPAYMENTS : customer_id
    CUSTOMERS ||--o{ TRANSACTIONS : customer_id
    CUSTOMERS ||--o{ PRODUCT_EVENTS : user_id
    CUSTOMERS ||--o{ SUPPORT_TICKETS : customer_id
    CUSTOMERS ||--o{ EXPERIMENT_ASSIGNMENTS : customer_id
    APPLICATIONS ||--o| LOANS : application_id
    LOANS ||--o{ REPAYMENTS : loan_id
    LOANS ||--o{ TRANSACTIONS : loan_id
    LOANS ||--o{ SUPPORT_TICKETS : loan_id
    REPAYMENTS ||--o{ TRANSACTIONS : repayment_id
    EXPERIMENTS ||--o{ EXPERIMENT_ASSIGNMENTS : experiment_id
```

Column-level detail: [data_dictionary.md](data_dictionary.md).

## 4. Pipeline orchestration

```mermaid
sequenceDiagram
    participant S as Scheduler (GitHub Actions / Task Scheduler)
    participant P as pipeline.py
    participant DQ as DQ framework
    participant W as DuckDB
    participant AI as AI analyst
    S->>P: weekly trigger (Mon 07:00 IST)
    P->>P: extract (+ lineage)
    P->>DQ: validate raw (profile only)
    P->>P: transform (repair / quarantine / log)
    P->>DQ: validate curated (gate)
    alt critical failure
        DQ-->>P: block
        P-->>S: exit 1 (run log + DQ report)
    else pass
        P->>W: rebuild core + marts
        P->>W: SQL analytics, KPIs, anomalies, experiments, segments
        P->>AI: fact sheet
        AI->>AI: Claude draft -> numeric grounding check -> retry / drop
        AI-->>P: executive_summary.md
        P-->>S: exit 0 + artifacts
    end
```

Each run writes `outputs/run_logs/run_<id>.json` with step status, duration and row counts.

## 5. AI analyst design

```mermaid
flowchart TB
    F[Fact sheet<br/>73 numbered facts with sources] --> C1[Claude: structured JSON summary<br/>each item cites fact ids]
    C1 --> G{Grounding check:<br/>every number present in a cited fact?}
    G -->|yes| R[Render Markdown with citations + sources appendix]
    G -->|no| RT[Targeted retry with the rejected items] --> C1
    RT -->|still failing after 2 retries| D[Drop the item, note it in the report] --> R
    Q[Question] --> C2[Claude with tools]
    C2 -->|run_sql| GU[SQL guard: SELECT-only, allow-listed tables,<br/>row cap, read-only + no external access]
    GU --> DB[(DuckDB)]
    DB --> C2
    C2 --> A[Answer JSON] --> G2{Every number in<br/>tool results?} --> OUT[Answer + SQL + verification status]
```

Why this design: LLMs are good at selecting and phrasing, unreliable at arithmetic and prone to plausible
invented figures. Pushing every calculation into SQL/Python and making the model cite governed facts turns
"trust the model" into "verify the model" - each number in a stakeholder document is traceable to a file.

## 6. Technology choices

| Need | Choice | Why |
|---|---|---|
| Warehouse | DuckDB | Columnar, PostgreSQL-flavoured SQL, zero infrastructure, enforces PK/FK; the SQL ports to Postgres/Snowflake with minor date-function changes |
| Storage format | Parquet (ZSTD) | Typed, compressed curated layer |
| Processing | pandas / numpy | Team-standard analyst tooling |
| Statistics / ML | scipy, scikit-learn | z-tests, power, chi-square; K-Means, silhouette |
| BI | Power BI | Organisation standard for executive reporting |
| LLM | Claude (Anthropic API) | Structured outputs + tool use; deterministic fallback keeps the pipeline LLM-optional |
| Orchestration | Python CLI + GitHub Actions / Windows Task Scheduler | Simple, observable, no extra services |

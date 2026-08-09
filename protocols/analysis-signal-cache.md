> **Status: active.** The fact-ledger split, finance profile, canonical
> cash-flow definition, and reconciliation gate are active. Policy state
> remains human-reviewed.

Outcome: Relevant analyses reuse current, source-linked facts instead of re-fetching or reconstructing the same evidence ad hoc.
Done when: A finance analysis can load a bounded fact bundle, distinguish reporting periods and metric definitions, detect stale or conflicting observations, and identify exactly which facts still require retrieval.
Evidence: Schema validation, deterministic bundle output, period-basis regression fixtures, idempotent ingestion tests, and harness smoke checks.
Output: An immutable private fact ledger under `$OV`, an ephemeral analysis bundle, and explicit source gaps or conflicts.

## Problem

The current system has durable event reports, source-verification reports, and
latest signal readings. Those surfaces preserve narrative evidence and policy
state, but they do not provide a normalized fact table keyed by entity, fiscal
period, metric definition, and source.

This gap makes repeated analysis expensive and error-prone. A search result may
surface a trailing-twelve-month number while a policy rule expects a standalone
quarter. A company-reported non-GAAP metric may also be mistaken for a
cross-company comparable metric. Both cases can produce a confident but
incorrect signal state.

The user's word "cache" maps to two different storage contracts:

1. A durable fact ledger is the source of truth for extracted observations.
2. A generated analysis bundle is an ephemeral, bounded read model over that
   ledger.

Raw downloads remain L1 cache. They must never be the only durable source for
an important fact. This follows the tier and cache rules in
`protocols/local-first-architecture.md` and the backend authority rules in
`protocols/backend-taxonomy.md`.

## Scope

The current scope covers financial reporting facts, with earnings and
cash-flow metrics as the first profile. The storage and query mechanism is
generic, but it does not normalize every market, macro, health, or career
signal.

"Every analysis" means every analysis whose selected route or explicit topic
requires a configured signal profile. Unrelated reflection, reading, health,
or planning sessions do not receive finance context.

The current scope supports:

- primary-source observations from regulatory filings and company investor
  relations material;
- standalone-quarter, year-to-date, full-year, and trailing-twelve-month
  period bases;
- reported source facts and generated derived metrics as distinct observations;
- company-specific metric definitions alongside canonical comparable
  definitions;
- missing, stale, contested, and superseded states;
- a bounded bundle for use before relevant analysis;
- append-only corrections with source lineage.

The current scope does not:

- replace the existing narrative signal engine;
- infer undisclosed metrics from weak proxies;
- treat analyst commentary as equivalent to a primary-source fact;
- make portfolio decisions;
- write generated bundles into the durable knowledge tiers.

## Storage and authority

The mechanism is split across the public harness and the private vault.

| Surface | Authority | Persistence | Contents |
|---|---|---:|---|
| Public harness | behavior | durable | schema, validators, query logic, metric-definition contracts, synthetic tests |
| Private vault fact ledger | factual source of truth | durable | observations, source locators, extraction metadata, revisions |
| Private vault policy files | interpretation | durable | thresholds, watchlists, action rules, manual overrides |
| `<paths.cache>/` | transport and read cache | ephemeral | downloaded source payloads and generated analysis bundles |
| Narrative signal reports | explanation and audit | durable | why a fact matters, thesis impact, decision history |

The exact private ledger path is configured outside the public repository. A
recommended layout is one immutable filing record per entity, reporting period,
and source identity:

```text
<configured-ledger>/
  earnings/
    <entity-id>/
      <period-end>/
        <source-id>.json
```

The ledger is intentionally not semantic-search-first. Numeric facts are
selected deterministically. A generated Markdown or JSON bundle gives an agent
the bounded context it needs.

## Observation contract

Each immutable source record has:

```json
{
  "schema_version": 1,
  "record_id": "<stable content-derived id>",
  "entity": {
    "id": "<canonical id>",
    "ticker": "<optional public symbol>",
    "fiscal_year_end": "<optional MM-DD>"
  },
  "event": {
    "kind": "earnings",
    "fiscal_period": "<company label>",
    "period_start": "YYYY-MM-DD",
    "period_end": "YYYY-MM-DD",
    "reported_at": "<RFC3339 timestamp>"
  },
  "source": {
    "type": "regulatory-filing | investor-relations",
    "url": "<primary URL>",
    "accession_or_document_id": "<stable source identity>",
    "available_at": "<RFC3339 public availability timestamp>",
    "retrieved_at": "<RFC3339 timestamp>"
  },
  "observations": [
    {
      "metric_id": "<canonical metric id>",
      "value": 0,
      "unit": "USD",
      "scale": 1,
      "period_basis": "quarter | ytd | fy | ttm | point_in_time",
      "observation_date": "<optional YYYY-MM-DD for point-in-time facts; defaults to event.period_end>",
      "scope": "consolidated | <segment id>",
      "kind": "reported",
      "definition_id": "<metric-definition id>",
      "verification": "primary-deterministic | primary-extracted | candidate"
    }
  ],
  "supersedes": []
}
```

Required invariants:

- The current durable ledger accepts `event.kind = earnings` only.
- `period_basis` is mandatory. A TTM value cannot satisfy a quarterly query.
- `definition_id` is mandatory for every stored observation.
- `observation_date` is allowed only for point-in-time facts. It defaults to
  `event.period_end`, is normalized into every point-in-time observation, and
  is part of the fact identity. Distinct observation dates never conflict or
  overwrite one another.
- Cash PP&E purchases (gross or net), explicit cash offsets, and finance-lease
  principal use strictly positive magnitudes. Operating cash flow and
  company-reported free cash flow remain signed values.
- Durable records contain source-reported facts only. They reject persisted
  derived values.
- The generated bundle names each derived formula and its source-record
  operands. Reported and derived observations never overwrite each other.
- Missing and undisclosed values are represented as explicit query outcomes,
  not numeric zeroes.
- Corrections create a new record with `supersedes`; prior records remain
  auditable.
- New records must state `source.available_at`.
- The idempotency key includes entity, period end, source identity, metric,
  definition, period basis, and any point-in-time observation date.

`source.available_at` records when a source became public and determines
whether a record belongs in a historical `--as-of` bundle. It is distinct from
`source.retrieved_at`, which records local ingestion. Legacy records without
`available_at` use `event.reported_at` as their availability timestamp.

## Metric definitions

Metric definitions are versioned and explicit. The first profile needs at
least:

- operating cash flow;
- cash purchases of property and equipment;
- proceeds or incentives netted against property and equipment purchases;
- finance-lease principal payments;
- company-reported free cash flow;
- canonical cash-capex free cash flow;
- lease-adjusted free cash flow;
- revenue, segment revenue, capex guidance, and disclosed backlog.

The system preserves all valid definitions. A policy threshold must bind to
one definition ID. The bundle may show adjacent definitions for comparison,
but it cannot silently substitute one for another.

For cross-company cash-flow comparison, the proposed default is:

```text
canonical_cash_capex_fcf_v1
  = quarterly operating cash flow
  - quarterly cash purchases of property and equipment (positive magnitude)
  + quarterly proceeds or incentives explicitly netted by the issuer
    (positive magnitude)
```

Lease-adjusted free cash flow remains a separate comparison view. A company
reported free-cash-flow figure remains a separate reported observation.
Finance-lease principal is also a positive magnitude when subtracted for the
lease-adjusted view. This convention prevents a signed cash-flow statement
presentation from reversing a derivation.

## Ingestion

Ingestion has three paths:

1. Deterministic primary-source adapter. Regulatory structured facts are
   normalized and can be marked `primary-deterministic`.
2. Primary-source extraction. An agent extracts a table or release value and
   records the source document identity. The result is `primary-extracted`
   after schema and source cross-checks pass.
3. Candidate capture. Secondary reporting or ambiguous source material can
   enter as `candidate`, but default policy queries do not treat it as a
   verified fact.

The public helper accepts declarative records and never executes commands
declared by private configuration. Source-specific adapters and private
watchlists remain in `$OV`.

Ingestion is atomic and idempotent:

- validate before write;
- refuse path escape and malformed source identities;
- no-op on an identical record;
- refuse a conflicting duplicate unless it names the prior record in
  `supersedes`;
- emit one machine-readable `written` or `unchanged` status; rejected records
  exit non-zero with a specific error.

## Read path

A relevant analysis begins with a deterministic preflight:

```text
signal facts bundle
  -> select configured profile
  -> select latest valid facts as of the requested date
  -> evaluate freshness and conflicts
  -> derive registered metrics
  -> return bounded JSON or Markdown
```

The bundle contains:

- `as_of` time and ledger fingerprint;
- selected entity and period;
- value, period basis, definition, and verification state for every fact;
- derivation formula and operand references;
- source links;
- stale, missing, contested, and superseded items;
- policy signals computed from named definition IDs;
- a retrieval plan containing only the unresolved gaps.

For a historical `as_of`, the bundle includes only records whose public
availability timestamp is at or before the cutoff. A correction therefore
does not erase the facts available before its publication.

Agents follow this order:

1. Read the bundle.
2. Reuse verified, current observations.
3. Browse only for missing, stale, or event-newer-than-ledger facts.
4. Ingest newly verified facts.
5. Regenerate the bundle before analysis.
6. Cite the primary source, not the bundle itself, in user-facing conclusions.

If the bundle cannot establish a required definition or period basis, the
signal result is `unknown`. It is never inferred from a nearby metric.

## Routing

The existing command and intent system gains a finance-analysis mode rather
than a new top-level skill. The mode invokes the configured signal profile
before researcher or scout work.

The same preflight rule applies to direct finance-analysis requests that do not
enter through the command router. This belongs in a provider-neutral analysis
protocol referenced by the canonical agent guidance.

Private configuration owns:

- which signal profiles exist;
- which entities belong to each profile;
- which metrics are required, optional, or entity-specific;
- freshness windows;
- the durable ledger location;
- the policy file and source-adapter mappings.

The public harness validates the configuration fields and enums it consumes.
Unknown fields are ignored for forward compatibility; unsupported signal
kinds, periods, source types, and verification states are rejected.

## Refresh

Refresh is event-driven first and periodic second:

- After a configured earnings release or filing, ingest the new event once.
- The weekly signal routine checks ledger freshness and lists missing events.
- An interactive analysis refreshes only gaps that could change its answer.
- A deterministic maintenance job may refresh transport caches without an
  LLM, but durable fact promotion still follows the ingestion contract.

The existing narrative collection and source-validation flows remain useful.
They should consume the fact bundle and write interpretation; they should not
become parallel numeric sources of truth.

## Migration

The initial migration backfills a bounded recent window for the configured
earnings universe. Migration does not rewrite policy state silently.

1. Import the latest two reporting periods for the initial entity set.
2. Validate period basis and source identity.
3. Recompute affected policy signals from their declared definition IDs.
4. Produce a reconciliation report against current manual readings.
5. Require human review for any changed signal state.
6. After reconciliation, leave manual fields only for genuine judgment,
   overrides, or currently unautomated evidence.

## Failure behavior

| Failure | Result |
|---|---|
| Ledger missing or empty | bundle returns explicit `no_records` retrieval gaps |
| Required event missing | bundle succeeds with an explicit retrieval gap |
| Source older than freshness policy | value is returned as stale and cannot be presented as current |
| Quarter and TTM both available | both remain visible; a quarterly query selects only quarter |
| Conflicting primary sources | result is contested; policy state is `unknown` |
| Formula operand missing | derived value is absent; required source metrics appear as retrieval gaps |
| Company-reported and canonical values differ | both are shown with distinct definition IDs |
| Adapter network failure | existing facts remain readable; no empty or zero record is written |

## Verification

Implementation is complete only when these checks pass:

- schema rejects missing period basis, definition, source identity, secondary
  claims of primary verification, non-positive derivation magnitudes, and
  persisted derived values;
- repeated identical ingestion is a no-op;
- a correction preserves and supersedes the prior record;
- a synthetic fixture containing quarterly and TTM free cash flow returns the
  correct one for each query;
- a synthetic fixture with cash capex and finance-lease principal preserves
  canonical, lease-adjusted, and company-reported definitions separately;
- point-in-time observations with distinct observation dates remain distinct
  and retain those dates in the resolved bundle;
- a policy signal becomes `unknown` when its selected definition is absent;
- bundle output is deterministic, bounded, and source-linked;
- historical `as_of` output excludes corrections not yet publicly available;
- finance routing selects the bundle preflight while unrelated routing does not;
- the existing signal scanner can consume the new bundle without duplicating
  numeric facts;
- privacy, harness lint, and harness smoke checks pass.

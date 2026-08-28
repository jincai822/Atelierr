Outcome: A relevant analysis starts from verified local facts, retrieves only
the gaps, and leaves a source-linked record for the next analysis.
Done when: The analysis bundle is current enough for the question, every
numeric claim resolves to a primary source, and policy-state changes are
reviewed rather than silently applied.
Evidence: `signal_facts.py bundle` output, ledger record IDs, source URLs, and
an explicit gaps or conflicts section.
Output: A bounded fact bundle plus the user-facing analysis.

## When this protocol applies

Use this protocol for company earnings, public-market cash flow, capital
expenditure, market-cycle, and configured investment-signal analysis. Do not
load market facts into unrelated reflection, health, reading, or personal
planning sessions.

The `$hi` router maps these requests to `intents.finance-analysis`. Direct
requests that bypass `$hi` still follow the same preflight.

## Preflight

Before web retrieval or agent dispatch, read
`$OV/_meta/signal_facts.toml`, resolve its `cache_dir` under `$OV`, and load
`<cache_dir>/finance-latest.json` when it exists. Then run the read-only
projection:

```bash
uv run scripts/atelier/signal_facts.py bundle \
  --profile finance \
  --format json
```

When the current turn has the applicable vault-write approval, add `--cache`
to refresh the reusable projection. Omitting `--cache` does not weaken the
analysis because the command still reads the durable ledger and returns the
same bounded bundle.

Read the returned:

- `as_of` timestamp and ledger fingerprint;
- latest events and explicit period bases;
- reported and derived definition IDs;
- configured signal states;
- conflicts, gaps, and `retrieval_required`.

`--as-of` is a public-information cutoff. A record is eligible only after its
`source.available_at` timestamp, never merely because it was later retrieved
into the local ledger. This preserves the pre-correction view for historical
analysis.

Reuse current primary-source observations. Do not semantically search for a
number already present in the deterministic bundle.

## Gap retrieval

When `retrieval_required` is true, the user's requested event is newer than
the latest ledger event, or an explicitly requested optional metric is absent
from the selected observations:

1. Retrieve only the missing or stale event from a regulatory filing or
   company investor-relations source.
2. Preserve quarter, YTD, FY, TTM, and point-in-time bases exactly as reported.
   Record the exact `observation_date` for point-in-time facts; when omitted,
   it normalizes to `event.period_end`. Never attach `observation_date` to a
   quarter, YTD, FY, or TTM fact. Encode cash PP&E purchases, explicit cash
   offsets, and finance-lease principal as positive magnitudes; keep operating
   cash flow and reported free cash flow signed.
3. Keep company-reported and canonical metric definitions separate.
4. Prepare one declarative source record.
5. After the applicable vault-write approval, run:

   ```bash
   uv run scripts/atelier/signal_facts.py ingest --file <candidate.json>
   ```

6. Regenerate the bundle before drawing conclusions.

Interactive ingestion remains a vault write and follows the normal approval
rule. A scheduled routine may ingest only when its existing procedure and
capability profile explicitly authorize that write.

## Analysis rules

- Cite the primary source in the user-facing answer. The bundle is provenance
  plumbing, not the citation target.
- A quarterly policy query cannot use a YTD, FY, or TTM observation.
- A company-reported metric cannot satisfy a canonical-definition query unless
  the definition IDs explicitly match.
- An undisclosed metric is `unknown`. Backlog is not retention; Cloud revenue
  is not AI-direct revenue.
- A contested fact or missing formula operand makes the affected conclusion
  `unknown`.
- If the ledger is stale but the network is unavailable, present the dated
  local fact and disclose the gap.

## Policy reconciliation

The bundle may compute configured policy signals from named definition IDs.
When that state differs from a manual policy reading:

1. Produce a reconciliation showing the old state, computed state, formula,
   periods, values, and primary sources.
2. Do not silently edit the policy file.
3. Ask the user to approve the state transition.
4. After approval, replace duplicated numeric text with the deterministic
   handler where the existing scanner supports it.

The implementation and storage reference is
[analysis-signal-cache.md](analysis-signal-cache.md).

# Track C evaluation protocol

Track C asks one question: does a semantic `DocumentPlan` improve report planning without weakening the proven Kordoc renderer path?

## Compared paths

- A: source + prompt -> rich Markdown
- C: source + prompt -> `DocumentPlan` -> deterministic Markdown mapper

Both paths end at the same existing Markdown/chart-fence boundary. The evaluator does not call Custom GPT Actions and does not change Kordoc, compatibility metadata, or HWPX validation.

## Case pack

`track_c_cases.json` contains five synthetic public-sector-style cases:

1. policy improvement: comparison table + metric/chart
2. budget execution: rates + table/chart/list
3. facility status: progress + risks
4. activity cost: group comparison
5. meeting action: table/list, explicitly no chart

Synthetic data keeps the evaluation reproducible and avoids coupling the PoC to a live work document.

## Run protocol

For each case, produce A and C from exactly the same `prompt` and `source_text`.

- Do not manually repair either output before scoring.
- Preserve the raw A Markdown and raw C plan JSON.
- Run `track_c_eval.py` on both.
- Record schema failures/retries separately for C.
- After the planner comparison is useful, pass both Markdown outputs through the same Kordoc/HWPX pipeline and record structural validation plus Windows Hancom results.
- Repeat each case three times when model-variance testing begins.

Example:

```bash
python track_c_eval.py \
  --cases track_c_cases.json \
  --case-id policy_improvement \
  --a-markdown results/policy_improvement_a.md \
  --c-plan results/policy_improvement_c.json
```

## Automatic signals

The harness intentionally uses simple, auditable signals:

- required term coverage
- required numeric literal coverage
- expected heading/table/chart/list coverage
- unnecessary chart penalty for cases that explicitly forbid charts
- advisory list of numeric literals appearing in the output but not the source

The unexpected-number list is a review aid, not an automatic hallucination verdict.

## Manual review

Automatic scoring cannot judge whether a chart is sensible or whether the report hierarchy is good. Review each A/C pair for:

- correct prioritization of important information
- appropriate table/chart choice
- readability and redundancy
- unsupported factual claims
- whether the C semantic blocks make later partial editing easier

## Go / No-Go gate

Track C remains a PoC until the comparison is complete.

GO requires all of the following:

- Plan -> Markdown mapping succeeds for every valid test plan.
- C does not reduce required-fact coverage versus A in a systematic way.
- C improves expected-structure coverage in at least 3 of the 5 cases, or matches A while showing a clear editability/consistency benefit.
- No systematic increase in unsupported numeric content.
- The same mapped Markdown continues to pass the existing Kordoc + compatibility + HWPX validation path.

NO-GO / pause if:

- C adds no measurable structure/consistency benefit over direct Markdown.
- semantic planning repeatedly loses source facts that A preserves.
- the schema must grow substantially just to express the five basic cases.
- Track C requires changes to the proven renderer or delays the separate Action transport investigation.

Do not move the gate after seeing results; change it only when a new requirement is independently justified.

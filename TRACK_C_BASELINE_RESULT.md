# Track C one-shot A/B baseline

## Purpose

Compare the existing direct-Markdown path (A) with DocumentPlan -> deterministic Markdown (C) using the five committed Track C evaluation cases.

This is a **one-shot baseline generated in the current ChatGPT development session**, not a repeated OpenAI API sampling experiment. It must not be used to claim statistical consistency or model-level superiority.

## Result

| Case | A score | C score | A unexpected numbers | C unexpected numbers |
|---|---:|---:|---:|---:|
| policy_improvement | 1.000 | 1.000 | 0 | 0 |
| budget_execution | 1.000 | 1.000 | 0 | 0 |
| facility_status | 1.000 | 1.000 | 0 | 0 |
| activity_cost | 1.000 | 1.000 | 0 | 0 |
| meeting_action | 1.000 | 1.000 | 0 | 0 |

Both modes preserved every required term and number and satisfied every committed structural expectation in all five cases.

## Interpretation

The current five-case evaluator does **not** demonstrate that DocumentPlan improves one-shot document quality over direct Markdown. The test set is easy enough that both paths reach the ceiling.

This is still useful evidence:

1. DocumentPlan -> Markdown can represent the tested report patterns without losing required content or structure.
2. The deterministic mapper does not reduce the baseline score for these cases.
3. There is currently **no evidence from this baseline** that Track C should replace direct Markdown merely for output quality.

## Next information-rich experiment

Do not add more block types yet. Shift the comparison to properties that DocumentPlan is intended to improve:

- structural validity before rendering;
- behavior under malformed/partial model output;
- edit locality and deterministic block targeting;
- cross-block numeric consistency risks;
- repeated-generation consistency once a real repeated model/API runner is available.

A specific weakness to test next is duplicated facts across metric/table/chart blocks. DocumentPlan v0.1 validates each block shape, but it does not yet prove that repeated representations of the same fact remain mutually consistent after an edit.

## Current decision

**Track C remains GO for bounded experimentation, not promotion to the production path.**

Promotion requires evidence that C improves reliability, editability, or consistency without regressing the proven Kordoc pipeline.

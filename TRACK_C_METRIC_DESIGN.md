# Track C derived metric design note

The v0.1 evidence probe proved that an aligned table/chart can contain 2400 -> 1200 while a metric block still says 40.0%, and the plan remains schema-valid.

The fix must not infer relationships from Korean labels or titles. A metric is checked against source data only when it carries an explicit optional derivation binding.

Initial supported derivation is intentionally narrow:

- kind: `percent_decrease`
- source chart title: exact match
- series: exact match
- from category: exact match
- to category: exact match

Unbound metrics remain free semantic values and are not guessed from neighboring blocks. No facts registry, formula language, fuzzy matching, or renderer change is introduced in this step.

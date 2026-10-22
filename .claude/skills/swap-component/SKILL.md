---
name: swap-component
description: Assess or perform a swap of one platform component (ingestion, MDM, warehouse, semantic layer, orchestration, BI, serving, AI) for another tool, using the contracts, the conformance tests and the golden answers. Use when asked whether tool X can replace a component, what a swap costs, or to run a swap drill.
---

1. Read the component in `docs/components.md` and `evaluation/components.yml`: its contract (C1-C7), swap cost, and the test a replacement must pass.
2. Explain what must hold for the candidate (PLAN.md §9.3 rules) and the couplings (warehouse ↔ semantic layer; transformation ↔ dbt).
3. To prove a swap rather than describe it: implement only the adapter the contract defines (a bronze adapter macro, an MDM provider writing C3, a `semantic_service` backend, the Power BI `LoadMart` function), never changes to neighbours.
4. Run the component's conformance test and `python -m evaluation.golden check` (or `--backend tsql`). Report pass/fail with numbers.
5. Record findings in a copy of `evaluation/scorecard.md`. Do not add commercial tools to the codebase unless the user asks explicitly.

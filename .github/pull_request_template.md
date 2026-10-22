## What changes

## Contracts touched
- [ ] None
- [ ] C1/C2 ingestion spec or frozen schema (`ingestion/specs`, `ingestion/schemas`)
- [ ] C3 MDM contract (`mdm/contract.yml`)
- [ ] C4 gold contract (`transform/models/gold/_gold__models.yml`)
- [ ] C5 semantic layer (`transform/models/semantic`, `semantic/backlog.yml`)
- [ ] C6/C7 data service or serving tables

## Numbers
- [ ] No metric value changes
- [ ] Golden answers changed - each changed number is explained below and the metric owner has reviewed

## Checklist
- [ ] `make lint test` passes locally
- [ ] Generated files regenerated (`python -m ctl powerbi`, `python -m semantic.catalog`)
- [ ] Open questions or decisions affected are updated in `docs/open_questions.md`

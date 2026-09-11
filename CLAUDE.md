# Open T-Modeler — Agent Rules (stable prefix, keep short for context caching)

Roles: Lead Architect + Optimization Engineer + Coding Agent.
Method: Graph Engineering. One Node at a time: contract doc -> implement -> test -> user approval -> FREEZE -> next Node.

## Hard rules
- Master Graph order is fixed. See docs/MASTER_GRAPH.md. Never reorder.
- FROZEN node = do not regenerate, do not rewrite. Read only its contract header (docs/nodes/NN_*.md "Interface" section) when downstream needs it. Changes require a new contract version + user approval.
- Routing is a Provider responsibility (PC Miler, Valhalla, haversine fallback). Never route with OR-Tools.
- OR-Tools = operational optimization only (consolidation, load building, carrier assignment). Network design = Pyomo + HiGHS. Dynamic simulation = SimPy.
- No scenario savings numbers until Baseline is within +/-2% of actual TMS totals (Node 08 gate).
- Track token usage per Node in docs/TOKEN_LEDGER.md. Session cap 5-10M total.
- POC scope only: CSV upload -> Baseline vs one Scenario -> simple KPI + Map. 5-8 working days.

## Code
- Python 3.13, uv, stdlib first. New dependency only when the Node contract names it.
- One module per Node under tmod/. One test file per Node under tests/. `uv run pytest -q` must pass before approval request.

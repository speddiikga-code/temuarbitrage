# Task board

One owner per task. Claim a task by adding your name and branch in your first commit, and update the status when it changes.
Rules are in [AGENTS.md](AGENTS.md).

| # | Task | Owner | Branch | Status |
|---|---|---|---|---|
| 1 | Phase 1 scanner: AliExpress + Naver Shopping + CSV sources, matching, pricing, CLI, CSV report | Claude | `claude/nice-edison-1ryaum` | done |
| 2 | Scan JSON export (contract for other tools) | Claude | `claude/nice-edison-1ryaum` | done |
| 3 | **Review workbench:** read scan JSON, show source vs. market listing side by side (photos, titles, prices), approve/reject each match, override shipping/fees/list price with live re-pricing through `arbitrage.pricing`, save `data/decisions.json` | GPT | `gpt/workbench` | proposed |
| 4 | **Compliance filter:** KC tiers (안전인증/안전확인/공급자적합성), children's products, 전파법, food/cosmetics/medical, batteries, brand blocklist; flag or drop in `scan` | Claude | `claude/compliance` | next |
| 5 | Korean listing copy (title/bullets rewrite, keyword) | unassigned | | later |
| 6 | Listing: Coupang WING + Naver Commerce API (needs a fixed Seoul IP) | unassigned | | later |
| 7 | Order sync: orders + 개인통관고유부호, purchase tasks, tracking back | unassigned | | later |
| 8 | Live smoke test with real Naver/AliExpress keys | owner | | waiting on keys |

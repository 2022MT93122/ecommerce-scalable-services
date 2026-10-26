# AI Assistance Log (Assignment 1 - Transparent Disclosure)

| Date | Member | Tool | Prompt / Task | Generated Aid | Human Review and Modification | Tested? |
|------|--------|------|---------------|---------------|--------------------------------|---------|
| 2026-10-25 | Dr. Sunanda Pandita | Antigravity AI | Initial project planning and handbook review | Starter structure, architecture notes | Refined service boundaries and isolation rules | Yes |
| 2026-10-26 | Dr. Sunanda Pandita | Antigravity AI | Atomic stock decrement query & hold lifecycle | Conditional SQL update and state machine logic | Adapted to SQLAlchemy 2.0 with PostgreSQL/SQLite compatibility, added custom idempotency duplicate check | Yes (pytest & 20-thread concurrency harness) |
| 2026-10-26 | Dr. Sunanda Pandita | Antigravity AI | Concurrency test harness and SQL proof script | Multi-threaded test script | Verified against 20 concurrent requests for 5 stock units, confirmed 5 accepted and 15 rejected with 0 final stock | Yes |

### Disclosure Statement
The team used generative AI tools for project planning, explanation of distributed systems concepts, initial code/test scaffolding, and editing assistance. All code and design decisions were reviewed and adapted by the named contributors, tested locally against real service instances, and verified.

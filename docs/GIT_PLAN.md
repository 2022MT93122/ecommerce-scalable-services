# Git Collaboration Plan and Attribution Log

## Branch Strategy
- `main`: Protected production trunk.
- `feature/inventory-service`: Dr. Sunanda Pandita (Owner P1 - Inventory & Concurrency).
- `feature/order-service`: Tarun (Owner P2 - Order & Integration).
- `feature/payment-notification`: Meghana Toutam (Owner P3 - Payment & Notification).

## Author Authentication
Each team member commits strictly using their linked institutional GitHub identity:
- **Sunanda**: `DrSunandaPandita <2025tm93132@wilp.bits-pilani.ac.in>`
- **Meghana**: `MeghanaToutam15 <2025tm93231@wilp.bits-pilani.ac.in>`
- **Tarun**: `2022MT93122 <2022MT93122@wilp.bits-pilani.ac.in>`

## Meghana's Authentic Commit Milestones
1. `docs(payment): document mock charge failure modes and API contracts`
2. `chore(mocks): scaffold payment and notification FastAPI services with health endpoints`
3. `feat(payment): implement charge persistence with database-level unique idempotency key`
4. `feat(notification): implement message recorder and mock delivery API`
5. `feat(payment): add SHA-256 fingerprint validation and duplicate charge replay (BR5)`
6. `feat(payment): add controlled simulation modes (slow, decline) and safe GET-by-key reconciliation`
7. `feat(notification): add simulated failure modes and best-effort non-blocking delivery (BR6)`
8. `test(payment): add unit tests for idempotency replay, payload conflict, and concurrent charges`
9. `test(notification): add unit tests for message persistence, deduplication, and error injection`
10. `test(resilience): implement Challenge 3A timeout backoff and payment reconciliation script`
11. `docs: add Challenge 3A evidence dossier, database state proof, and personal reflection`

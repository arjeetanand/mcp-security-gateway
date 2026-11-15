# Local demo repair

- [x] Reproduce the obsolete-header smoke failure against the JWT gateway.
- [x] Use signed local reader, writer, and admin tokens; make repeated smoke runs request fresh approvals.
- [x] Add in-process workflow and launcher ownership regression checks.
- [x] Run the prior 50-scenario in-process gateway evaluation.
- [x] Provide a loopback-only launcher with owned-process restart and stop checks.
- [x] Verify start, restart, repeat smoke runs, stop, and refusal of an unrelated listener locally.
- [x] Record each child before readiness waits; clean up on interruption and retain ownership for a child that does not stop.
- [x] Report when a stuck child's ownership cannot be saved, rather than claiming a record exists.
- [x] Clear only confirmed-stopped child records while preserving runtime data and any unconfirmed child.
- [x] Verify interrupted local test startup and a subsequent restart and smoke run.
- [x] Update JWT, audit-scope, port, and run instructions.
- [x] Receive authorization to push and open a pull request targeting `main`.
- [ ] Merge only after the required checks and explicit approval.

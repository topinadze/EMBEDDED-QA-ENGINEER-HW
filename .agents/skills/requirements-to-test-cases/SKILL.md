---
name: requirements-to-test-cases
description: "Analyze embedded-device requirements and translate them into traceable, observable manual or automated test cases. Use when reviewing a PRD, planning QA coverage, or creating/updating a requirements-to-tests matrix."
---

# Requirements to test cases

Turn product requirements into test cases whose expected outcomes can be observed and whose coverage can be traced back to the source.

## Procedure

1. Find the authoritative requirement source (PRD, issue, acceptance criteria, or user-approved behavior). Record requirement IDs and version constraints exactly.
2. For a new assignment, firmware, or PRD, first derive the intended system and bench workflow from the current authoritative materials: device/board, wiring and peripherals, operator actions, host tools, connection/control path, setup/teardown, and evidence expected. Do not assume this is the same product workflow with only firmware fixes.
3. For each behavior, specify:
   - unique test-case ID and concise objective;
   - requirement reference;
   - preconditions and required firmware/device state;
   - actions and input values;
   - expected UART/API/state output;
   - physical observation, if UART cannot prove the behavior;
   - cleanup, reboot, or persistent-data effects;
   - evidence to retain and execution mode.
4. Identify regression cases affected by changed requirements and previously reported defects; only carry forward a bug expectation when its evidence and firmware applicability support it. Do not assume a defect is fixed or unchanged solely because the firmware version advanced.
5. Cover positive, negative, boundary, and relevant state-transition cases. Include only meaningful equivalence classes; do not invent unsupported requirements.
6. Classify a case as automated when observable evidence is machine-verifiable, interactive when a person must operate hardware or observe a physical effect, or mixed when both are needed.
7. Mark ambiguous or untestable acceptance criteria as open questions or gaps. Ask before deciding behavior that changes the product contract.
8. Maintain bidirectional traceability: every in-scope requirement maps to one or more cases, and each case points to its requirement. Keep report/checklist status separate from test availability.

## New assignment or release baseline

- Treat the current approved PRD, bench instructions, and confirmed device-reported firmware as authoritative; never infer the workflow, version, or behavior from filenames or prior releases.
- Use previous PRDs, tests, bugs, drivers, fixtures, and reports as references for possible reuse, not as requirements. Compare baselines only to identify relevant deltas and reusable coverage after understanding the new workflow. Carry old behavior forward only when compatibility or regression coverage is in scope.
- For a new PRD in an existing project, use this order and keep the outputs separate:
  1. Analyze the new PRD on its own. Extract its system/bench workflow, requirement IDs, actors, preconditions, actions, expected outcomes, constraints, and ambiguities without importing assumptions from the old PRD.
  2. Analyze the previous baseline PRD and create an explicit requirement correspondence map. Classify each new requirement as direct match, partial/changed match, no known match, or unclear; also identify old requirements that are removed or have no new counterpart. Cite both source IDs and explain the basis for each proposed correspondence.
  3. Only after reviewing that map, compare historical bugs and their tests/evidence against the new requirements. Classify each relationship as direct, partial/possible, unrelated, or unresolved, and explain why. Similar wording or shared hardware alone is not evidence that a prior bug applies.
  4. Use the supported correspondences to identify reusable tests and regression candidates. Do not port old tests or defect expectations until their observable behavior, bench workflow, setup, and evidence requirements are confirmed compatible with the new PRD.
- Keep the new-PRD analysis, PRD-to-PRD correspondence map, and bug/test relationship map as distinct artifacts or report sections. Label inferred links and unresolved questions explicitly; ask the user when a decision would change scope or expected behavior.
- Before implementation, map the new workflow to the harness: identify which fixtures, drivers, pytest markers, launchers, setup/teardown, firmware guards, and evidence/report formats still apply. Replace or adapt outdated assumptions; update every affected surface consistently.
- Keep results attributable to the exact assignment, bench setup, firmware, and run. Run collection/static validation first; execute serial, interactive, OTA, flashing, or persistent-state checks only with explicit user authorization and confirmed preconditions.
- If the new firmware is unavailable, keep implementation and execution status distinct (`NOT RUN`); do not invent results or mark a requirement passed.

## Evidence and status rules

- `NOT RUN` means no execution evidence exists; a test implementation alone is not a result.
- `PARTIAL` means some, but not all, specified observations or steps were verified.
- Mark `PASS` only after all required assertions and physical observations are evidenced.
- Record firmware version, date, and artifact paths for hardware results.
- Do not claim a bug is fixed or absent from missing or inconclusive evidence.
- When editing an acceptance report, follow the assignment's required deliverable structure as well as its authoritative behavior specification.
- Keep checklist results, bug details, and bug/version matrix consistent. Carry legacy bug IDs or statuses into a new assignment only when a documented requirement/evidence mapping supports them; mark a regression only when both a prior fix and later recurrence are evidenced.
- Verify artifact timestamps and run scope before calling a result “latest”; distinguish full-suite runs from focused reruns. A skipped precondition is not a product failure, and `NOT RUN` exploration is not evidence that no findings exist.

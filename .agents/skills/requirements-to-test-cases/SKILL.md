---
name: requirements-to-test-cases
description: "Analyze embedded-device requirements and translate them into traceable, observable manual or automated test cases. Use when reviewing a PRD, planning QA coverage, or creating/updating a requirements-to-tests matrix."
---

# Requirements to test cases

Turn product requirements into test cases whose expected outcomes can be observed and whose coverage can be traced back to the source.

## Procedure

1. Find the authoritative requirement source (PRD, issue, acceptance criteria, or user-approved behavior). Record requirement IDs and version constraints exactly.
2. Split each requirement into independently verifiable behaviors. Identify actors, device state, inputs, outputs, timing, persistence, and hardware dependencies.
3. For each behavior, specify:
   - unique test-case ID and concise objective;
   - requirement reference;
   - preconditions and required firmware/device state;
   - actions and input values;
   - expected UART/API/state output;
   - physical observation, if UART cannot prove the behavior;
   - cleanup, reboot, or persistent-data effects;
   - evidence to retain and execution mode.
4. Cover positive, negative, boundary, and relevant state-transition cases. Include only meaningful equivalence classes; do not invent unsupported requirements.
5. Classify a case as automated when observable evidence is machine-verifiable, interactive when a person must operate hardware or observe a physical effect, or mixed when both are needed.
6. Mark ambiguous or untestable acceptance criteria as open questions or gaps. Ask before deciding behavior that changes the product contract.
7. Maintain bidirectional traceability: every in-scope requirement maps to one or more cases, and each case points to its requirement. Keep report/checklist status separate from test availability.

## Evidence and status rules

- `NOT RUN` means no execution evidence exists; a test implementation alone is not a result.
- `PARTIAL` means some, but not all, specified observations or steps were verified.
- Mark `PASS` only after all required assertions and physical observations are evidenced.
- Record firmware version, date, and artifact paths for hardware results.
- Do not claim a bug is fixed or absent from missing or inconclusive evidence.

---
name: allure-test-reporting
description: "Create self-explanatory embedded pytest tests and readable Allure reports using requirement metadata, action-oriented steps, and useful evidence attachments. Use when adding tests, improving report quality, or organizing test evidence."
---

# Allure reporting and self-explanatory tests

## Procedure

1. Add applicable epic, feature, story, title, and requirement/bug references using the existing repository conventions.
2. Make the test title understandable in the report without reading the implementation. Parameterized titles should identify the tested value.
3. Wrap meaningful scenario phases in `with allure.step(...)` or reusable driver actions in `@allure.step(...)`. Name steps as observable actions/checks, not implementation trivia.
4. Keep assertions near the step that establishes their evidence. Use useful failure messages that state expected and actual outcomes.
5. Attach relevant command responses, manual observations, and complete UART transcripts using the existing driver/fixture lifecycle. Avoid redundant attachments for every trivial local value.
6. Keep the evidence channel explicit: operator feedback (including console/Telegram manual checks), UART assertions, Allure attachments, and persisted per-test transcripts are related but not interchangeable. A displayed or acknowledged prompt is not a physical PASS.
7. For DZ17 lamp checks, identify the expected color and RGB reference in the step/attachment; a sample image or RGB number helps the operator but does not prove the LED's physical output.
8. Ensure fixture teardown steps (for example recovery reboot) are included in Allure when they affect device state.

## Quality checks

- A report reader should understand setup, action, expected result, and actual result from the step tree.
- Never report an operator response as proof of a UART assertion, or UART state as proof of a physical LED observation.
- Use consistent requirement and bug IDs between test metadata and `REPORT.md`.
- Never attach or persist Wi-Fi passwords, tokens, or other secrets. Redact evidence before committing.
- Keep report status grounded in executed results, not merely in collected or implemented tests.

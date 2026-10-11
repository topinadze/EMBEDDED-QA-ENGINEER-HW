from __future__ import annotations

import allure
import pytest


def _attach_manual_feedback(
    instruction: str, result: str, comment: str | None = None
) -> None:
    lines = [f"Check: {instruction}", f"Result: {result}"]
    if comment:
        lines.append(f"Comment: {comment}")
    allure.attach(
        "\n".join(lines),
        name="Manual verification",
        attachment_type=allure.attachment_type.TEXT,
    )


@allure.step("Manual verification: {instruction}")
def verify_manually(instruction: str) -> bool:
    """Pause for an observed physical result and record it in Allure."""
    print(f"\n{'=' * 60}")
    print("MANUAL CHECK REQUIRED")
    print(instruction)
    print(f"{'=' * 60}")

    comment: str | None = None
    while True:
        try:
            response = input("Observed result? [y] pass / [n] fail / [c] add comment: ")
        except EOFError:
            _attach_manual_feedback(instruction, "NOT RECORDED (no interactive input)")
            pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")

        response = response.strip().casefold()
        if response in {"y", "n"}:
            passed = response == "y"
            result = "PASS" if passed else "FAIL"
            _attach_manual_feedback(instruction, result, comment)
            print(f"Manual check recorded: {result}")
            if not passed:
                failure_message = [f"Manual check failed: {instruction}"]
                if comment:
                    failure_message.append(f"Operator comment: {comment}")
                pytest.fail("\n".join(failure_message), pytrace=False)
            return True
        if response == "c":
            try:
                comment = input("Add an observation or failure detail: ").strip()
            except EOFError:
                _attach_manual_feedback(
                    instruction, "NOT RECORDED (comment input unavailable)"
                )
                pytest.fail("Manual comment input is unavailable; run pytest with -s.")
            continue

        print("Enter y, n, or c.")

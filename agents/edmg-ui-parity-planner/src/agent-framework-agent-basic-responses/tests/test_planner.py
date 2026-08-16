import unittest

from planner import OUTPUT_SECTIONS, PLANNER_INSTRUCTIONS, build_planner_instructions


class PlannerInstructionsTests(unittest.TestCase):
    def test_output_sections_are_present_in_order(self) -> None:
        instructions = build_planner_instructions()
        positions = [instructions.index(section) for section in OUTPUT_SECTIONS]

        self.assertEqual(positions, sorted(positions))

    def test_backend_preservation_is_explicit(self) -> None:
        self.assertIn("FastAPI, Python, CUDA, and TensorRT", PLANNER_INSTRUCTIONS)
        self.assertIn("must not duplicate\nor replace backend compute", PLANNER_INSTRUCTIONS)
        self.assertIn("backend conversion", PLANNER_INSTRUCTIONS)

    def test_gap_contract_is_complete(self) -> None:
        for field in (
            "Gap ID and priority",
            "User impact",
            "Electron reference capability",
            "Target UI surface",
            "Remediation steps",
            "Dependencies",
            "Risks",
            "Acceptance criteria",
        ):
            self.assertIn(field, PLANNER_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()

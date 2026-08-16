import os
import unittest
from unittest.mock import patch

from main import get_required_setting


class RequiredSettingTests(unittest.TestCase):
    def test_uses_first_configured_setting(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FOUNDRY_PROJECT_ENDPOINT": "https://foundry.example/project",
                "AZURE_AI_PROJECT_ENDPOINT": "https://azure.example/project",
            },
            clear=True,
        ):
            value = get_required_setting(
                "FOUNDRY_PROJECT_ENDPOINT",
                "AZURE_AI_PROJECT_ENDPOINT",
            )

        self.assertEqual(value, "https://foundry.example/project")

    def test_uses_fallback_setting(self) -> None:
        with patch.dict(
            os.environ,
            {"AZURE_AI_PROJECT_ENDPOINT": "https://azure.example/project"},
            clear=True,
        ):
            value = get_required_setting(
                "FOUNDRY_PROJECT_ENDPOINT",
                "AZURE_AI_PROJECT_ENDPOINT",
            )

        self.assertEqual(value, "https://azure.example/project")

    def test_reports_all_missing_setting_names(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "FOUNDRY_PROJECT_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT",
            ):
                get_required_setting(
                    "FOUNDRY_PROJECT_ENDPOINT",
                    "AZURE_AI_PROJECT_ENDPOINT",
                )


if __name__ == "__main__":
    unittest.main()

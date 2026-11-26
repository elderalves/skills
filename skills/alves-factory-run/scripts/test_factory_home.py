"""Run with: python -m unittest discover <this-dir>."""

import unittest
from pathlib import Path

from factory_home import factory_home


class FactoryHomeTest(unittest.TestCase):
    def test_defaults_to_alves_factory_in_home(self):
        self.assertEqual(factory_home({}), Path.home() / ".alves-factory")

    def test_blank_variable_uses_default(self):
        self.assertEqual(factory_home({"ALVES_FACTORY_HOME": "  "}), Path.home() / ".alves-factory")

    def test_variable_overrides_and_expands_home(self):
        self.assertEqual(factory_home({"ALVES_FACTORY_HOME": "~/sync/factory"}),
                         Path.home() / "sync" / "factory")


if __name__ == "__main__":
    unittest.main()

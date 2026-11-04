"""Registry definitions, typed schemas and advertised permissions must agree."""
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from check_registry_literals import repeated_literal_keys,runtime_sources
from langgraph_migration.science import SCIENCE_CONTRACTS,SCIENCE_MENUS,SCIENCE_DESCRIPTIONS
from team import DESCRIPTIONS


class RegistryIntegrityTests(unittest.TestCase):
    def test_literal_overwrite_detection_and_live_runtime_sources(self):
        self.assertEqual(len(repeated_literal_keys("registry={'tool':1,'tool':2}")),1)
        self.assertEqual(repeated_literal_keys("registry={'a':1, 'b':2}"),[])
        for path in runtime_sources(ROOT):
            with self.subTest(file=str(path.relative_to(ROOT))):
                self.assertEqual(repeated_literal_keys(path.read_text()),[])

    def test_every_advertised_role_tool_has_one_schema_and_description(self):
        descriptions={**DESCRIPTIONS,**SCIENCE_DESCRIPTIONS}
        for role,names in SCIENCE_MENUS.items():
            self.assertEqual(len(names),len(set(names)),role)
            for name in names:
                with self.subTest(role=role,tool=name):
                    self.assertIn(name,SCIENCE_CONTRACTS)
                    self.assertTrue(descriptions.get(name))
                    self.assertEqual(SCIENCE_CONTRACTS[name].model_config.get('extra'),'forbid')


if __name__=='__main__':unittest.main()

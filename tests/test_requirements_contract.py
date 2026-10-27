"""Deployment dependency contract; no network or provider calls."""
from pathlib import Path
import unittest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]

def entries(name):
    return [
        line.strip()
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

class RequirementsContractTests(unittest.TestCase):
    def test_deployment_requirements_are_flat_and_exactly_pinned(self):
        names = set()
        for line in entries("requirements.txt"):
            with self.subTest(requirement=line):
                self.assertFalse(line.startswith("-"), "Nested files/options break deployment parsing")
                requirement = Requirement(line)
                self.assertIsNone(requirement.url)
                specs = list(requirement.specifier)
                self.assertEqual(len(specs), 1)
                self.assertEqual(specs[0].operator, "==")
                self.assertNotIn("*", specs[0].version)
                name = canonicalize_name(requirement.name)
                self.assertNotIn(name, names)
                names.add(name)
        self.assertIn("fastapi", names)
        self.assertIn("google-genai", names)
        self.assertIn("supabase", names)

    def test_flat_deployment_file_matches_locked_baseline(self):
        self.assertEqual(entries("requirements.txt"), entries("requirements.lock.txt"))

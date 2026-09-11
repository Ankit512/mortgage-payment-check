import unittest

from scripts.check_scenarios import check_scenarios


class ScenarioUploadTests(unittest.TestCase):
    def test_hand_authored_packs_reproduce_through_upload_and_graph(self):
        report = check_scenarios()
        self.assertEqual(report["uploads_verified"], 12)
        self.assertEqual(len(report["invalid_upload_checks"]), 2)


if __name__ == "__main__":
    unittest.main()

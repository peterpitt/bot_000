import unittest

from consultancy.advisors import ADVISORS, org_chart
from consultancy.council import Council, load_base_prompt, select_advisors, triage
from consultancy.llm import OfflineBackend


class CouncilTest(unittest.TestCase):
    def test_twelve_advisors_all_in_departments(self):
        self.assertEqual(len(ADVISORS), 12)
        self.assertEqual(sum(len(v) for v in org_chart().values()), 12)
        self.assertEqual([a.id for a in ADVISORS if a.symbolic], ["void"])

    def test_triage(self):
        self.assertEqual(triage("隨便聊聊"), ["business_model"])
        self.assertIn("dispatch", triage("要不要把設計外包給其他公司"))
        self.assertIn("finance", triage("現金流不夠怎麼辦"))

    def test_selection_size_and_finance_leads(self):
        for topics in (["brand"], ["finance", "dispatch"], ["automation"], ["business_model"]):
            chosen = select_advisors(topics)
            self.assertTrue(4 <= len(chosen) <= 6, topics)
            self.assertEqual(len({a.id for a in chosen}), len(chosen))
        ids = {a.id for a in select_advisors(["brand", "finance"])}
        self.assertTrue({"pluto", "polaris"} <= ids)

    def test_prompt_strips_citations_and_includes_ops_rules(self):
        self.assertNotIn("[cite:", load_base_prompt())
        result = Council(backend=OfflineBackend()).consult("外包網站專案的報價怎麼抓")
        system = result.messages[0]["content"]
        self.assertIn("金流紅線", system)
        self.assertIn("本次召集顧問", system)
        self.assertIn("離線草稿", result.answer)


if __name__ == "__main__":
    unittest.main()

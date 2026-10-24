"""End-to-end tests for the mock pipeline (no network, no API key)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm import MockLLM  # noqa: E402
from src.orchestrator import Orchestrator  # noqa: E402
from src.schemas import Scenario  # noqa: E402

SCENARIO = ROOT / "data" / "scenarios" / "ecommerce_customer_service.yaml"


class PipelineTest(unittest.TestCase):
    def _run(self, out_root: Path):
        scenario = Scenario.from_yaml(SCENARIO)
        llm = MockLLM(seed=scenario.seed)
        orchestrator = Orchestrator(
            scenario=scenario,
            llm=llm,
            out_root=out_root,
            mode="mock",
            chart_path=out_root / "chart.png",
        )
        return scenario, orchestrator.run()

    def test_scenario_weights_sum_to_one(self):
        scenario = Scenario.from_yaml(SCENARIO)
        self.assertAlmostEqual(sum(d.weight for d in scenario.dimensions), 1.0, places=6)
        self.assertEqual(sum(scenario.category_mix.values()), scenario.n_cases)

    def test_end_to_end_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenario, result = self._run(Path(tmp))
            self.assertTrue((result.run_dir / "report.md").exists())
            self.assertTrue((result.run_dir / "run.json").exists())
            self.assertTrue((result.run_dir / "task_ledger.jsonl").exists())
            self.assertTrue((result.run_dir / "evaluations.csv").exists())
            self.assertTrue((result.run_dir / "summary.csv").exists())
            payload = json.loads((result.run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["analysis"]["summaries"]), len(scenario.models))
            self.assertEqual(len(payload["evaluations"]), len(scenario.models) * scenario.n_cases)
            model_names = [m.name for m in scenario.models]
            self.assertIn(payload["analysis"]["recommendation"], model_names)
            for row in payload["evaluations"]:
                for value in row["scores"].values():
                    self.assertGreaterEqual(value, 1.0)
                    self.assertLessEqual(value, 5.0)
            report = (result.run_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("## 结论", report)
            self.assertIn("mock", report)

    def test_reproducible_with_same_seed(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            _, a = self._run(Path(first))
            _, b = self._run(Path(second))
            self.assertEqual(
                [row["overall"] for row in a.analysis["summaries"]],
                [row["overall"] for row in b.analysis["summaries"]],
            )

    def test_constraints_filter_the_quality_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self._run(Path(tmp))
            by_model = {row["model"]: row for row in result.analysis["summaries"]}
            self.assertTrue(by_model["mock-balanced"]["meets_constraints"])
            self.assertFalse(by_model["mock-quality"]["meets_constraints"])
            self.assertEqual(result.analysis["recommendation"], "mock-balanced")

    def test_ledger_has_five_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self._run(Path(tmp))
            records = [
                json.loads(line)
                for line in result.ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(
                [record["agent"] for record in records],
                ["planner", "case_designer", "evaluator", "analyst", "reporter"],
            )
            self.assertTrue(all(record["status"] == "ok" for record in records))


if __name__ == "__main__":
    unittest.main()

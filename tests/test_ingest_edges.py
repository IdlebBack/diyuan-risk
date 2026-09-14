"""事件导入的来源、去重与原子写入回归；不联网、不改项目事件库。"""

from __future__ import annotations

import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from chainshield import ingest
from chainshield.repository import read_event_csv
from chainshield.signals import Signal


class IngestEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "nested" / "events_live.csv"

    @staticmethod
    def row(title: str = "合成编码器信号", url: str = "https://example.test/item-1") -> dict:
        return {"title": title, "summary": "仅用于离线测试", "date": "2026-09-13", "url": url}

    @staticmethod
    def signal(index: int = 1) -> Signal:
        return Signal(
            title=f"合成编码器信号{index}", summary="仅用于离线测试",
            source="测试来源", source_id=f"fixture-{index}",
            url=f"https://example.test/item-{index}",
            published="Tue, 08 Sep 2026 08:00:00 GMT", country_hint="日本",
        )

    def test_replace_failure_preserves_original_file_and_caller_rows(self) -> None:
        ingest.save_events([self.row()], self.path)
        original_bytes = self.path.read_bytes()
        incoming = [self.row("新增合成信号", "https://example.test/item-2")]
        original_input = copy.deepcopy(incoming)

        with patch.object(ingest.os, "replace", side_effect=OSError("synthetic replacement failure")):
            with self.assertRaises(OSError):
                ingest.save_events(incoming, self.path)

        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(incoming, original_input)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_first_save_failure_does_not_leave_destination_or_temporary_file(self) -> None:
        incoming = [self.row()]
        original_input = copy.deepcopy(incoming)
        with patch.object(ingest.os, "replace", side_effect=OSError("synthetic replacement failure")):
            with self.assertRaises(OSError):
                ingest.save_events(incoming, self.path)
        self.assertFalse(self.path.exists())
        self.assertEqual(incoming, original_input)
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_duplicate_backfills_stored_id_without_rewriting_file(self) -> None:
        first = self.row()
        ingest.save_events([first], self.path)
        original_bytes = self.path.read_bytes()
        duplicate = self.row("同一来源改写标题")
        self.assertEqual(ingest.save_events([duplicate], self.path), 0)
        self.assertEqual(duplicate["event_id"], first["event_id"])
        self.assertEqual(duplicate["title"], first["title"])
        self.assertEqual(self.path.read_bytes(), original_bytes)

    def test_duplicates_within_batch_share_one_persisted_id(self) -> None:
        rows = [self.row(url=""), self.row(url="")]
        rows[1]["summary"] = "重复条目的另一个摘要"
        self.assertEqual(ingest.save_events(rows, self.path), 1)
        self.assertEqual(rows[0]["event_id"], rows[1]["event_id"])
        self.assertEqual(len(read_event_csv(self.path)), 1)

    def test_append_preserves_manual_status_and_custom_columns(self) -> None:
        manual = ingest.normalize_event(self.row())
        manual.update(event_id="EVT-L040", status="active", reviewed_by="synthetic-reviewer")
        self.path.parent.mkdir(parents=True)
        pd.DataFrame([manual]).to_csv(self.path, index=False, encoding="utf-8-sig")
        incoming = self.row("新增合成信号", "https://example.test/item-2")

        self.assertEqual(ingest.save_events([incoming], self.path), 1)
        stored = read_event_csv(self.path).set_index("event_id")
        self.assertEqual(stored.loc["EVT-L040", "status"], "active")
        self.assertEqual(stored.loc["EVT-L040", "reviewed_by"], "synthetic-reviewer")
        self.assertEqual(incoming["event_id"], "EVT-L041")
        self.assertEqual(incoming["status"], "verify")

    def test_same_process_concurrent_writes_do_not_lose_records(self) -> None:
        rows = [self.row(f"合成信号{index}", f"https://example.test/{index}") for index in range(8)]
        with ThreadPoolExecutor(max_workers=4) as workers:
            added = list(workers.map(lambda row: ingest.save_events([row], self.path), rows))
        stored = read_event_csv(self.path)
        self.assertEqual(sum(added), len(rows))
        self.assertEqual(len(stored), len(rows))
        self.assertEqual(stored["event_id"].nunique(), len(rows))

    def test_model_cannot_override_original_source_metadata(self) -> None:
        signal = self.signal()
        parsed = {
            "title": "模型整理的合成标题", "summary": "模型整理的合成摘要",
            "source": "模型虚构来源", "source_id": "invented-source",
            "url": "https://invented.example.test/article", "published": "1999-01-01",
            "date": "1999-01-01", "status": "active", "source_kind": "fact",
            "confidence": "high",
        }
        original_parsed = copy.deepcopy(parsed)
        row = ingest.signal_to_event(signal, parsed)
        for key in ("source", "source_id", "url", "published"):
            self.assertEqual(row[key], getattr(signal, key))
        self.assertEqual(row["date"], "2026-09-08")
        self.assertEqual(row["status"], "verify")
        self.assertEqual(parsed, original_parsed)

    def test_uncertain_dependency_does_not_reappear_from_model_summary_on_save(self) -> None:
        signal = Signal(title="一般产业新闻（合成）", summary="并未指明具体零部件", source="测试来源")
        row = ingest.signal_to_event(signal, {
            "title": "模型整理标题", "summary": "模型摘要提到编码器", "related_dependencies": "",
        })
        self.assertEqual(row["related_dependencies"], "")
        ingest.save_events([row], self.path)
        self.assertEqual(row["related_dependencies"], "")
        self.assertEqual(read_event_csv(self.path).iloc[0]["related_dependencies"], "")

    def test_missing_publication_is_explicitly_labeled_as_import_date(self) -> None:
        signal = self.signal()
        signal.published = "not-a-date"
        with patch.object(ingest, "date") as clock:
            clock.today.return_value = date(2026, 9, 13)
            row = ingest.signal_to_event(signal, None)
        self.assertEqual(row["date"], "2026-09-13")
        self.assertEqual(row["published"], "not-a-date")
        self.assertIn("导入日期", row["notes"])
        self.assertIn("非事件确认时间", row["notes"])

    def test_unknown_or_nonfinite_effects_remain_non_actionable(self) -> None:
        cases = (("unknown_effect", 4), ("transit_delay", float("inf")),
                 ("transit_delay", float("nan")), ("transit_delay", -1),
                 ("transit_delay", True))
        for kind, value in cases:
            with self.subTest(kind=kind, value=str(value)):
                row = ingest.normalize_event({
                    **self.row(), "effect_kind": kind, "effect_value": value, "severity": 5,
                })
                self.assertEqual(row["effect_kind"], "")
                self.assertEqual(row["effect_value"], 0)
                self.assertEqual(ingest.normalize_event(row)["effect_kind"], "")
                self.assertEqual(row["status"], "verify")

    def test_one_extraction_failure_does_not_abort_remaining_signals(self) -> None:
        signals = [self.signal(index) for index in range(1, 4)]
        responses = [
            TimeoutError("synthetic private diagnostic"),
            {"ok": False, "data": None, "warnings": []},
            {"ok": True, "data": {"title": "第三条合成标题", "summary": "第三条合成摘要"}, "warnings": []},
        ]
        with patch.object(ingest, "extract_risk_event", side_effect=responses) as extract:
            rows, details = ingest.run_signal_pipeline(signals)
        self.assertEqual(extract.call_count, 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(details), 3)
        self.assertEqual(rows[0]["title"], signals[0].title)
        self.assertEqual(rows[2]["title"], "第三条合成标题")
        self.assertTrue(all(row["status"] == "verify" for row in rows))
        self.assertNotIn("synthetic private diagnostic", str(details))
        self.assertEqual(details[0]["mode"], "fallback")
        self.assertTrue(details[2]["ok"])
        self.assertEqual([row["url"] for row in rows], [signal.url for signal in signals])

    def test_invalid_extraction_response_is_isolated(self) -> None:
        with patch.object(ingest, "extract_risk_event", side_effect=["not-a-dict", {"ok": False, "data": None}]):
            rows, details = ingest.run_signal_pipeline([self.signal(1), self.signal(2)])
        self.assertEqual(len(rows), 2)
        self.assertEqual(details[0]["mode"], "fallback")
        self.assertEqual(rows[1]["source_id"], "fixture-2")

    def test_empty_batch_does_not_call_model(self) -> None:
        with patch.object(ingest, "extract_risk_event") as extract:
            self.assertEqual(ingest.run_signal_pipeline([]), ([], []))
        extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()

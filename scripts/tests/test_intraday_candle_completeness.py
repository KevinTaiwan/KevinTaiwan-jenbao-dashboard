#!/usr/bin/env python3
"""Offline regression tests: off-grid or still-open OHLC cannot be published."""
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collect_intraday_market import completed_bar_boundary,normalize,sanitize_saved_candles,UTC,TPE

def bar(stamp):
    return {"time":stamp,"open":100.0,"high":101.0,"low":99.0,"close":100.5}

class CandleCompleteness(unittest.TestCase):
    def test_off_grid_partial_rejected(self):
        self.assertFalse(completed_bar_boundary("2026-11-24T10:50:40+08:00"))
        self.assertFalse(completed_bar_boundary("2026-11-23T15:33:22-05:00"))
        self.assertTrue(completed_bar_boundary("2026-11-24T10:45:00+08:00"))
    def test_normalization_keeps_confirmed_bar_only(self):
        raw=[bar("2026-11-24T10:45:00+08:00"),bar("2026-11-24T10:50:40+08:00")]
        rows=normalize(raw,"2026-11-24",TPE,dt.time(9),dt.time(13,30))
        self.assertEqual([r["time"] for r in rows],["2026-11-24T10:45:00+08:00"])
    def test_legacy_sanitization_preserves_valid_history(self):
        valid=bar("2026-11-24T10:45:00+08:00")
        old={"market":"taiex","date":"2026-11-24","source":"Yahoo 5m","sourceDelayMinutes":15,
             "candles":[valid,bar("2026-11-24T10:50:40+08:00")]}
        clean,changed=sanitize_saved_candles({"taiex":old},dt.datetime(2026,11,24,3,12,tzinfo=UTC))
        self.assertEqual(changed,["taiex"])
        self.assertEqual(len(clean["taiex"]["candles"]),1)
        self.assertEqual(clean["taiex"]["latest"]["lastCandleTime"],valid["time"])
    def test_all_invalid_removes_only_market(self):
        old={"market":"taiex","candles":[bar("2026-11-24T10:50:40+08:00")]}
        clean,changed=sanitize_saved_candles({"taiex":old},dt.datetime(2026,11,24,3,12,tzinfo=UTC))
        self.assertEqual(changed,["taiex"])
        self.assertNotIn("taiex",clean)
if __name__=="__main__":
    unittest.main()

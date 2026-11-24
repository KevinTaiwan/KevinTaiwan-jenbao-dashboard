#!/usr/bin/env python3
"""Regression tests: only metadata time changes are safe to skip."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from market_material_write import material_view,write_public_if_materially_changed

class TestMaterialGate(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p=Path(self.temp.name)/"sample.json"
    def write(self,obj,kind="market-history"):
        return write_public_if_materially_changed(self.p,obj,kind)
    def test_metadata_only_does_not_rewrite(self):
        x={"rows":[{"date":"2026-11-23","taiex":36811.89}],"cutoff":"2026-11-23","generatedAt":"old","twseTurnoverAudit":{"generatedAt":"old","mismatchCount":0},"backfillAudit":{"collectedAt":"old","after":{"taiex":1}}}
        self.assertTrue(self.write(x))
        before=self.p.read_bytes()
        y=copy.deepcopy(x)
        y.update(generatedAt="new",cutoff="2026-11-24")
        y["twseTurnoverAudit"]["generatedAt"]="new"
        y["backfillAudit"]["collectedAt"]="new"
        self.assertFalse(self.write(y))
        self.assertEqual(before,self.p.read_bytes())
    def test_new_trading_day_is_material(self):
        x={"rows":[{"date":"2026-11-23","taiex":36811.89}]}
        self.assertTrue(self.write(x))
        x["rows"].append({"date":"2026-11-24","taiex":36850})
        self.assertTrue(self.write(x))
    def test_revised_prior_observation_is_material(self):
        x={"rows":[{"date":"2026-11-23","taiex":36811.89}]}
        self.assertTrue(self.write(x))
        x["rows"][0]["taiex"]=36812
        self.assertTrue(self.write(x))
    def test_provenance_and_quality_are_material(self):
        x={"rows":[],"source":"TWSE","twseTurnoverAudit":{"generatedAt":"old","mismatchCount":0}}
        self.assertTrue(self.write(x))
        x["source"]="TWSE updated"
        self.assertTrue(self.write(x))
        x["twseTurnoverAudit"]["mismatchCount"]=1
        self.assertTrue(self.write(x))
    def test_snapshot_timestamp_only_is_skipped(self):
        x={"updatedAt":"old","market":{"marginMaintenance":126.92},"dataStatus":"partial"}
        self.assertTrue(self.write(x,"market-data"))
        raw=self.p.read_bytes()
        x["updatedAt"]="new"
        self.assertFalse(self.write(x,"market-data"))
        self.assertEqual(raw,self.p.read_bytes())
        x["dataStatus"]="verified"
        self.assertTrue(self.write(x,"market-data"))
    def test_material_view_pure_and_schema_guard(self):
        x={"generatedAt":"old","rows":[]}
        self.assertNotIn("generatedAt",material_view(x,"market-history"))
        self.assertEqual(x["generatedAt"],"old")
        with self.assertRaises(ValueError):material_view(x,"unknown")
if __name__=="__main__":unittest.main()

"""Offline V18 regressions; fixtures are synthetic, never published observations."""
import datetime as dt
import pathlib
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import refresh_market_history as r

def html(rows, title="扣除ETF資券進出行情"):
    return "<h1>"+title+"</h1><table>"+ "".join("<tr>"+"".join("<td>"+str(x)+"</td>" for x in row)+"</tr>" for row in rows)+"</table>"
def row(day, ratio, close):
    return [day,"3985","51",""+ratio,"1","2","3",close,"4","5"]

class V18Tests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(r.parse_wantgoo_ex_etf(html([row("11/26","139.67%","39,151.81")]),dt.date(2026,11,26),{"2026-11-26":39151.81}),{"2026-11-26":139.67})
    def test_reject_wrong_scope(self):
        with self.assertRaises(ValueError):
            r.parse_wantgoo_ex_etf(html([], "全部資券進出行情"),dt.date(2026,11,26),{})
    def test_reject_wrong_close_and_missing_percent(self):
        data=html([row("11/26","139.67%","38,000"),row("11/25","131.35","38,195.43")])
        self.assertEqual(r.parse_wantgoo_ex_etf(data,dt.date(2026,11,26),{"2026-11-26":39151.81,"2026-11-25":38195.43}),{})
    def test_future_and_year_rollover(self):
        data=html([row("01/03","130%","40,000"),row("12/31","140％","40,001")])
        self.assertEqual(r.parse_wantgoo_ex_etf(data,dt.date(2026,1,2),{"2026-01-03":40000,"2025-12-31":40001}),{"2025-12-31":140.0})
    def test_conflicting_duplicate(self):
        with self.assertRaises(RuntimeError):
            r.parse_wantgoo_ex_etf(html([row("11/26","139.67%","39,151.81"),row("11/26","140%","39,151.81")]),dt.date(2026,11,26),{"2026-11-26":39151.81})
    def test_existing_observation_not_overwritten(self):
        with patch.object(r,"TODAY",dt.date(2026,11,27)),patch.object(r,"TW_CUTOFF",dt.date(2026,11,26)),patch.object(r,"OBS",{"taiex":{"2026-11-26":39151.81},"marginMaintenanceExEtf":{"2026-11-26":139.67}}),patch.object(r,"get",return_value=html([row("11/26","140%","39,151.81")])):
            r.fetch_wantgoo_ex_etf()
            self.assertEqual(r.OBS["marginMaintenanceExEtf"]["2026-11-26"],139.67)
if __name__=="__main__":unittest.main()

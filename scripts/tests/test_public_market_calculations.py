import datetime as dt
import math
import statistics
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from public_market_calculations import index_metrics,ratio20,pairs_checked

def pairs(values):
    return [((dt.date(2020,1,1)+dt.timedelta(days=i)).isoformat(),v) for i,v in enumerate(values)]
def metrics(values):
    return index_metrics([{"date":d,"close":v} for d,v in pairs(values)])

class Tests(unittest.TestCase):
    def test_flat(self):
        r=metrics([100]*253)
        self.assertEqual(r["movingAverages"]["240"],100)
        self.assertEqual(r["windows"]["252"]["annualizedVolatilityPct"],0)
        self.assertEqual(r["windows"]["252"]["maxDrawdownPct"],0)
    def test_drawdown_and_vol(self):
        r=metrics([100,110,88]+[88]*18)["windows"]["20"]
        self.assertAlmostEqual(r["annualizedVolatilityPct"],statistics.stdev([.1,-.2]+[0]*18)*math.sqrt(252)*100,places=5)
        self.assertEqual(r["maxDrawdownPct"],-20)
    def test_missing(self):
        r=metrics([100]*240)
        self.assertEqual(r["windows"]["252"]["availableReturns"],239)
        self.assertIsNone(r["windows"]["252"]["annualizedVolatilityPct"])
    def test_ratio(self):
        r=ratio20(pairs([2]*20+[6]),"bp")
        self.assertEqual(r["latestOverPrior20Mean"],3)
        self.assertEqual(r["latestMinusPrior20Mean"],4)
    def test_signed(self):
        r=ratio20(pairs([0]*20+[1]),"bp")
        self.assertIsNone(r["latestOverPrior20Mean"])
        self.assertEqual(r["latestMinusPrior20Mean"],1)
        self.assertIsNone(ratio20(pairs([1]*20+[-1]),"bp")["latestOverPrior20Mean"])
    def test_invalid(self):
        for rows in [[("2020-01-01",1),("2020-01-01",2)],[("2020-01-01",float("nan"))]]:
            with self.assertRaises(ValueError):pairs_checked(rows)
        with self.assertRaises(ValueError):metrics([0])

import math,unittest
from ac_metrics import analyze
class MetricsTest(unittest.TestCase):
    def test_single_pole(self):
        rows=[]
        for i in range(601):
            f=10**(i/100);h=100/(1+1j*f/1000);rows.append((f,h.real,h.imag))
        r=analyze(rows,True,True)
        self.assertAlmostEqual(r['sampled_gain_db'],40,places=4)
        self.assertAlmostEqual(r['relative_3db_crossings'][0]['frequency_hz'],1000,delta=1)
        self.assertAlmostEqual(r['descending_unity_crossings'][0]['frequency_hz'],1000*math.sqrt(9999),delta=15)
        self.assertAlmostEqual(r['descending_unity_crossings'][0]['phase_margin_deg'],90.573,delta=.02)
    def test_transfer_not_loop(self):
        r=analyze([(1,2,0),(10,.5,0)])
        self.assertNotIn('phase_margin_deg',r['descending_unity_crossings'][0])
    def test_no_crossing(self):
        r=analyze([(1,2,0),(2,1.9,0)])
        self.assertEqual(r['descending_unity_crossings'],[])
        self.assertEqual(r['relative_3db_crossings'],[])
    def test_reject_bad_data(self):
        for rows in [[(1,1,0)],[(2,1,0),(1,1,0)],[(1,0,0),(2,1,0)],[(1,float('nan'),0),(2,1,0)]]:
            with self.assertRaises(ValueError):analyze(rows)
    def test_sign_gate(self):
        with self.assertRaises(ValueError):analyze([(1,2,0),(2,1,0)],True)
    def test_negative_margin(self):
        def v(f,mag,p):return (f,mag*math.cos(math.radians(p)),mag*math.sin(math.radians(p)))
        r=analyze([v(1,2,-170),v(10,.5,-230)],True,True)
        self.assertAlmostEqual(r['descending_unity_crossings'][0]['phase_margin_deg'],-20)
if __name__=='__main__':unittest.main()

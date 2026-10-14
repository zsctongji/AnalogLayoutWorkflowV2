import unittest
from inspect_report import inspect


def report(result='CORRECT', layout='/run/layout.gds', source='/run/source.sp', extra=''):
    return '''L V S   R E P O R T
LAYOUT NAME: %s ('TOP')
SOURCE NAME: %s ('TOP')
CURRENT DIRECTORY: /run
CALIBRE VERSION: v2019.3_15.11
OVERALL COMPARISON RESULTS
# %s #
----------------------
%s
SUMMARY
Total CPU Time: 1 sec
Total Elapsed Time: 2 sec
''' % (layout, source, result, extra)


class ReportTests(unittest.TestCase):
    def test_match_never_signoff(self):
        r = inspect(report(), 'LVS completed. CORRECT.')
        self.assertEqual(r['status'], 'REPORT_MATCH_UNVERIFIED')
        self.assertFalse(r['verified_match'])

    def test_mismatch(self):
        r = inspect(report('INCORRECT', extra='INCORRECT PORTS\nPROPERTY ERRORS'))
        self.assertEqual(r['status'], 'REPORT_MISMATCH')
        self.assertEqual(len(r['discrepancy_sections']), 2)

    def test_self_comparison(self):
        self.assertEqual(inspect(report(layout='/run/source.sp'))['status'], 'INVALID_COMPARISON')

    def test_alias_path(self):
        self.assertEqual(inspect(report(layout='./source.sp'))['status'], 'INVALID_COMPARISON')

    def test_same_data_warning(self):
        self.assertEqual(inspect(report(extra='Warning: Source and layout refer to the same data.'))['status'], 'INVALID_COMPARISON')

    def test_truncated(self):
        self.assertEqual(inspect(report().split('SUMMARY')[0])['status'], 'INCOMPLETE')

    def test_unrecognized(self):
        self.assertEqual(inspect('CORRECT')['status'], 'INCOMPLETE')

    def test_fatal(self):
        self.assertEqual(inspect(report(), 'FATAL: bad extraction')['status'], 'EXECUTION_FAILED')

    def test_conflict(self):
        self.assertEqual(inspect(report(), 'LVS completed. INCORRECT.')['status'], 'INCOMPLETE')

    def test_cap(self):
        self.assertEqual(inspect(report(extra='Report truncated'))['status'], 'INCOMPLETE')

    def test_warning_preserved(self):
        r = inspect(report(extra='Warning: unresolved device'))
        self.assertIn('Warning: unresolved device', r['warning_error_lines'])
        self.assertFalse(r['verified_match'])

    def test_banner_not_random_word(self):
        self.assertEqual(inspect(report('INCORRECT', extra='Warning: CORRECT is not established'))['status'], 'REPORT_MISMATCH')


if __name__ == '__main__':
    unittest.main()

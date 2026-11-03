import unittest

import ticket_status as ts


class TicketStatusTests(unittest.TestCase):
    def test_claimed_name_uses_display_name(self):
        self.assertEqual(ts.claimed_channel_name("Abdel Ouahmed"), "🟡-abdel-ouahmed")

    def test_claimed_name_strips_symbols(self):
        self.assertEqual(ts.claimed_channel_name("  Steve!! "), "🟡-steve")

    def test_claimed_name_fallback(self):
        self.assertEqual(ts.claimed_channel_name("!!!"), "🟡-staff")

    def test_claimed_name_fits_discord_limit(self):
        name = ts.claimed_channel_name("a" * 200)
        self.assertLessEqual(len(name), ts.NAME_LIMIT)
        self.assertTrue(name.startswith("🟡-"))
        self.assertFalse(name.endswith("-"))

    def test_fixed_status_names(self):
        self.assertEqual(ts.RESOLVED_NAME, "🟢-resolved")
        self.assertEqual(ts.HIGHER_NAME, "🔴-higher-up-needed")
        self.assertEqual(ts.BUG_NAME, "🟣-bug-report")
        for name in (ts.RESOLVED_NAME, ts.HIGHER_NAME, ts.BUG_NAME):
            self.assertLessEqual(len(name), ts.NAME_LIMIT)

    def test_close_deadline_adds_hours(self):
        self.assertEqual(ts.close_deadline(2, 1000.9), 1000 + 2 * 3600)

    def test_close_deadline_rejects_out_of_range(self):
        for hours in (0, 169, -1, True, False):
            with self.assertRaises(ts.TicketStatusError):
                ts.close_deadline(hours, 0)

    def test_seconds_until_is_never_negative(self):
        self.assertEqual(ts.seconds_until(50, 80), 0)
        self.assertEqual(ts.seconds_until(80, 50), 30)

    def test_transcript_filename_drops_emoji(self):
        self.assertEqual(ts.transcript_filename("🟡-abdel-ouahmed", "12"), "ticket-12-abdel-ouahmed.txt")
        self.assertEqual(ts.transcript_filename("🟢-resolved", ""), "resolved.txt")


if __name__ == "__main__":
    unittest.main()

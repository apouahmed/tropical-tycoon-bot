"""Command builders reject anything that is not a single console action."""

import unittest

import staff_actions as actions


class StaffActionsTest(unittest.TestCase):
    def test_profile_and_move_use_the_name_once(self) -> None:
        self.assertEqual(
            actions.profile_commands(".Steve"),
            ("balance .Steve", "lp user .Steve info"),
        )
        self.assertEqual(actions.move_command("Alex", "hub"), "gens send Alex hub")

    def test_rejects_command_injection_in_names(self) -> None:
        for bad in ("Steve\nkick Alex", "Steve; say hi", "../ops", "a" * 17, ""):
            with self.assertRaises(actions.ActionError):
                actions.minecraft_name(bad)

    def test_grants_keep_a_delivery_id_at_the_end(self) -> None:
        tx = "tx:discord-123"
        self.assertEqual(
            actions.keys_command("Alex", 2, "monthly", tx),
            "gens keys Alex monthly 2 tx:discord-123",
        )
        self.assertEqual(
            actions.booster_command("Alex", "sell", 50, 30, tx),
            "gens booster Alex sell 50 30 free discord tx:discord-123",
        )
        self.assertEqual(
            actions.store_command("Alex", "mogul", tx),
            "gens store Alex mogul tx:discord-123",
        )
        self.assertEqual(
            actions.pet_command("Alex", "Hermit Crab", 3, "support fix", tx),
            "pets give Alex hermit_crab 3 support fix tx:discord-123",
        )

    def test_events_match_the_live_rotation(self) -> None:
        self.assertEqual(
            actions.event_command("start:gen-overload:15"),
            "gens event start gen-overload 15",
        )
        self.assertEqual(actions.event_command("stop"), "gens event stop")
        with self.assertRaises(actions.ActionError):
            actions.event_command("start:fishing-frenzy:5")

    def test_announce_and_kick_drop_newlines(self) -> None:
        self.assertEqual(actions.announce_command("Hello\nthere"), "say Hello there")
        self.assertEqual(actions.kick_command("Alex", "afk farm"), "kick Alex afk farm")
        with self.assertRaises(actions.ActionError):
            actions.announce_command("§")


if __name__ == "__main__":
    unittest.main()

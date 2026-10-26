"""Rank sync: LuckPerms text, role changes, and link codes."""

import unittest

import rank_sync as ranks


LP_MOGUL = """
[LP] Showing parents for Steve:
- default
- mogul
- captain
- islander
"""

LP_GUIDE = """
Parent Groups:
    - guide
    - default
"""


class RankSyncTest(unittest.TestCase):
    def test_highest_store_wins_when_lower_ranks_are_inherited(self) -> None:
        groups = ranks.parse_groups(LP_MOGUL)
        self.assertEqual(ranks.highest_store(groups), "Mogul")
        self.assertIsNone(ranks.highest_staff(groups))
        self.assertIn("default", groups)
        self.assertNotIn("modifier", ranks.parse_groups("some modifier text"))

    def test_plan_replaces_store_role_and_keeps_hand_assigned_staff(self) -> None:
        plan = ranks.plan_roles({"Islander", "Guide", "Member"}, ranks.parse_groups(LP_MOGUL), None)
        self.assertEqual(plan.store, "Mogul")
        self.assertIn("Mogul", plan.add)
        self.assertIn("Islander", plan.remove)
        self.assertNotIn("Guide", plan.remove)
        self.assertIsNone(plan.managed_staff)

    def test_plan_moves_a_staff_role_this_bot_assigned(self) -> None:
        plan = ranks.plan_roles({"Guide"}, ranks.parse_groups(LP_GUIDE.replace("guide", "mod")), "Guide")
        self.assertIn("Mod", plan.add)
        self.assertIn("Guide", plan.remove)
        self.assertEqual(plan.managed_staff, "Mod")

    def test_donater_channels(self) -> None:
        rooms = {room.name: room for room in ranks.RANK_ROOMS}
        self.assertEqual(set(rooms), {ranks.DONATER_CHANNEL, ranks.DONATER_PLUS_CHANNEL})
        self.assertEqual(rooms[ranks.DONATER_CHANNEL].allow, ("Islander", "Surfer"))
        self.assertNotIn("Captain", rooms[ranks.DONATER_CHANNEL].allow)
        plus = rooms[ranks.DONATER_PLUS_CHANNEL]
        self.assertEqual(plus.allow, ("Captain", "Tycoon", "Mogul"))
        self.assertNotIn("Islander", plus.allow)
        self.assertNotIn("+", plus.name)
        self.assertTrue(plus.name.startswith("donater"))
        self.assertEqual(ranks.RANK_CHANNEL_RENAMES["below-captain"], ranks.DONATER_CHANNEL)
        self.assertEqual(ranks.RANK_CHANNEL_RENAMES["above-captain"], ranks.DONATER_PLUS_CHANNEL)
        self.assertIn("captain", ranks.RETIRED_RANK_CHANNELS)

    def test_failed_lookup_is_not_treated_as_no_rank(self) -> None:
        self.assertFalse(ranks.groups_response_ok("Could not find user Steve"))
        self.assertFalse(ranks.groups_response_ok(""))
        self.assertTrue(ranks.groups_response_ok(LP_MOGUL))
        self.assertTrue(ranks.player_offline("No player was found"))
        self.assertTrue(ranks.whisper_failed("Unknown command"))
        self.assertFalse(ranks.whisper_failed(""))

    def test_link_code_is_single_use_and_names_cannot_be_stolen(self) -> None:
        book = ranks.LinkDirectory()
        code, error = book.start("10", "Steve", "AB12CD", now=1000)
        self.assertIsNone(error)
        self.assertEqual(code, "AB12CD")
        again, error = book.start("10", "Steve", "ZZZZZZ", now=1001)
        self.assertEqual(again, "AB12CD")
        self.assertIsNone(error)
        name, error = book.confirm("10", "ab12cd", now=1002)
        self.assertEqual(name, "Steve")
        self.assertIsNone(error)
        _code, error = book.start("11", "steve", "CD34EF", now=1003)
        self.assertIn("already linked", error or "")
        self.assertIsNone(book.confirm("10", "AB12CD", now=1004)[0])

    def test_message_command_rejects_a_broken_name(self) -> None:
        command = ranks.link_message_command(".Steve", "AB12CD")
        self.assertTrue(command.startswith("msg .Steve Discord link code: AB12CD"))
        with self.assertRaises(staff_actions_error()):
            ranks.link_message_command("Steve\nsay hi", "AB12CD")


def staff_actions_error():
    import staff_actions

    return staff_actions.ActionError


if __name__ == "__main__":
    unittest.main()

"""Pure checks for the staff handbook and private-channel rules. No Discord connection."""

import unittest

import discord

import staff_discord as staff


class StaffDiscordTests(unittest.TestCase):
    def test_private_channel_is_for_staff_except_the_owner(self):
        owner = 10
        self.assertFalse(staff.holds_team_role(["Owner"], owner, owner))
        self.assertFalse(staff.holds_team_role(["Member"], 2, owner))
        self.assertTrue(staff.holds_team_role(["Guide"], 2, owner))
        self.assertTrue(staff.holds_team_role(["Mod", "Member"], 2, owner))
        self.assertTrue(staff.holds_team_role(["Admin"], 2, owner))
        self.assertTrue(staff.holds_team_role(["Owner"], 3, owner))

    def test_higher_rank_sees_lower_rooms(self):
        self.assertTrue(staff.rank_at_least("Admin", "Mod"))
        self.assertTrue(staff.rank_at_least("Mod", "Mod"))
        self.assertFalse(staff.rank_at_least("Guide", "Mod"))
        self.assertEqual(staff._MODE_VIEW["mod"], "Mod")
        self.assertEqual(staff._MODE_SEND["docs"], "Admin")
        self.assertEqual(staff._MODE_VIEW["docs"], "Guide")

    def test_vent_name_and_topic_roundtrip(self):
        self.assertEqual(staff.vent_channel_name("Alex Staff"), "vent-alex-staff")
        self.assertEqual(staff.vent_channel_name("🌴"), "vent-staff")
        topic = staff.vent_topic(99, True)
        self.assertEqual(staff.topic_user_id(topic), 99)
        self.assertIn("open=1", topic)
        self.assertEqual(staff.topic_user_id(staff.vent_topic(99, False)), 99)
        self.assertIsNone(staff.topic_user_id("just a topic"))

    def test_handbook_fits_discord_limits(self):
        mentions = {"conduct": "<#1>", "ranks": "<#2>", "ladder": "<#3>"}
        sections = staff.handbook_sections("Tropical Tycoon", None, mentions)
        self.assertEqual(
            set(sections),
            {"start-here", "onboarding", "handbook", "conduct", "ranks", "ladder", "cases", "appeals", "desk"},
        )
        embeds = staff.staff_handbook_embeds("Tropical Tycoon", None, mentions)
        self.assertGreaterEqual(len(embeds), 10)
        blob = "\n".join(
            (embed.title or "") + (embed.description or "") + "\n".join(
                field.name + field.value for field in embed.fields
            )
            for embed in embeds
        )
        for phrase in (
            "1 hour",
            "7 days",
            "Store ranks",
            "Islander",
            "Floodgate",
            "Punishment Appeal",
            "IGN:",
            "chargeback",
            "/gens give",
            "Creative and other gamemodes",
            "no `/co lookup`",
        ):
            self.assertIn(phrase.lower(), blob.lower(), phrase)
        self.assertNotIn("coreprotect", blob.lower())
        self.assertNotIn("/co i", blob.lower())
        self.assertNotIn("/co rollback", blob.lower())
        self.assertIn("<#1>", blob)
        for embed in embeds:
            self.assertLessEqual(len(embed), 6000, embed.title)
            self.assertLessEqual(len(embed.title or ""), 256)
            self.assertLessEqual(len(embed.description or ""), 4096)
            self.assertLessEqual(len(embed.fields), 25)
            for field in embed.fields:
                self.assertLessEqual(len(field.name), 256)
                self.assertLessEqual(len(field.value), 1024)
                self.assertGreater(len(field.value), 0)

    def test_layout_covers_the_workplace(self):
        rooms = [
            (logical, kind)
            for _category, channels in staff.STAFF_LAYOUT
            for logical, _topic, _mode, kind in channels
        ]
        names = [name for name, _kind in rooms]
        for required in (
            "start-here", "onboarding", "handbook", "conduct", "ranks", "ladder",
            "cases", "appeals", "desk", "staff-news", "staff-chat", "staff-voice",
            "guide-chat", "mod-chat", "admin-chat",
        ):
            self.assertIn(required, names)
        self.assertEqual(dict(rooms)["staff-voice"], "voice")
        self.assertFalse(staff.docs_are_current("tt-staff-docs=1", "conduct"))
        self.assertTrue(staff.docs_are_current(staff.channel_docs_marker("conduct"), "conduct"))

    def test_highest_rank_and_brief(self):
        self.assertIsNone(staff.highest_rank(["Member", "Islander"]))
        self.assertEqual(staff.highest_rank(["Guide", "Mod"]), "Mod")
        self.assertEqual(staff.highest_rank(["Admin", "Guide"]), "Admin")
        brief = staff.rank_brief_embed("Tropical Tycoon", None, "Guide")
        self.assertIn("1 hour", brief.description)
        self.assertNotIn("permaban", brief.description.lower())
        mod = staff.rank_brief_embed("Tropical Tycoon", None, "Mod")
        self.assertIn("7 days", mod.description)
        self.assertIn("cannot permaban", mod.description.lower())

    def test_punishment_ladder_matches_public_rule_count(self):
        self.assertEqual(len(staff.PUNISHMENT_LADDER), 22)
        self.assertEqual(staff.PUNISHMENT_LADDER[0][0], "Spam, flooding, caps")
        self.assertEqual(staff.PUNISHMENT_LADDER[-1][0], "Staff disrespect")

    def test_staff_server_is_the_one_requested(self):
        self.assertEqual(staff.STAFF_GUILD_ID, 1567210660516073504)

    def test_permission_pairs_hide_everyone_and_let_a_rank_speak(self):
        hidden = discord.PermissionOverwrite(view_channel=False)
        speak = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
        allow, deny = hidden.pair()
        self.assertGreater(deny.value, 0)
        self.assertEqual(allow.view_channel, False)
        allow, deny = speak.pair()
        self.assertTrue(allow.view_channel)
        self.assertTrue(allow.send_messages)
        self.assertFalse(deny.view_channel)


if __name__ == "__main__":
    unittest.main()

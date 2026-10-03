"""Saving a channel form must never write a masked credential back as the secret.

The channels page renders a credential as a mask and posts that mask straight
back on the next save. Every save path therefore has to recognise the mask and
leave the stored secret alone. Those guards counted four consecutive stars,
while ``_mask_secret`` emits one star per hidden character - so a credential of
9 to 11 characters came back as a one-to-three star mask that the guard read as
a real secret. The save then persisted the mask, and the next connect attempt
used a credential the user never typed and cannot recover from the UI.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channel.web.api.channels import ChannelsHandler


def _secret(length):
    return ("ABCD" + "efgh" + "ijklmnopqrstuvwx")[:length]


class MaskedSecretRoundTripTest(unittest.TestCase):
    """The guard has to agree with the mask it is meant to recognise."""

    def test_a_mask_is_recognised_at_every_length_the_mask_covers(self):
        for length in range(9, 25):
            with self.subTest(length=length):
                masked = ChannelsHandler._mask_secret(_secret(length))
                self.assertTrue(
                    ChannelsHandler._is_masked_secret(masked),
                    f"a {length}-character credential masks to {masked!r}, which "
                    "the save guard would store back over the real secret",
                )

    def test_a_real_secret_is_not_mistaken_for_a_mask(self):
        for length in (1, 6, 8, 9, 12, 24):
            with self.subTest(length=length):
                self.assertFalse(
                    ChannelsHandler._is_masked_secret(_secret(length)),
                    "a plaintext credential must be saved, not skipped",
                )

    def test_empty_values_are_skipped(self):
        # An empty secret means "leave what is stored alone", which is what the
        # guards did with `not value` before they grew a star count.
        self.assertTrue(ChannelsHandler._is_masked_secret(""))
        self.assertTrue(ChannelsHandler._is_masked_secret(None))

    def test_a_secret_containing_stars_is_still_saved(self):
        # A star in the middle of a real credential is not a mask: the masked
        # run has to be the whole middle. "AB*CD*EFGH" has a real "D" in it.
        self.assertFalse(ChannelsHandler._is_masked_secret("AB*CD*EFGH"))
        self.assertFalse(ChannelsHandler._is_masked_secret("ABCD*EFGH-IJKL"))

    def test_skipping_a_value_never_discards_anything(self):
        # The property the save paths actually rely on: whatever the predicate
        # skips, masking it again would have been a no-op - so skipping loses
        # no information. That is what makes it safe for the guard to accept a
        # shape wider than one specific star count.
        for length in range(1, 40):
            with self.subTest(length=length):
                for value in (_secret(length), _secret(length).replace("e", "*")):
                    if not ChannelsHandler._is_masked_secret(value):
                        continue
                    self.assertEqual(
                        ChannelsHandler._mask_secret(value),
                        value,
                        f"{value!r} is skipped, but masking it would have changed it",
                    )

    def test_every_save_path_shares_the_predicate(self):
        # The three call sites used to carry three copies of the star count, so
        # they have to be replaced together for the guard to mean one thing.
        import inspect

        from channel.web.api import channels as channels_api

        source = inspect.getsource(channels_api)
        self.assertFalse(
            '"*" * 4 in' in source,
            "a save path still counts stars instead of asking the shared predicate",
        )
        self.assertEqual(
            source.count("self._is_masked_secret(value)"),
            3,
            "expected the shared predicate at all three save paths",
        )


if __name__ == "__main__":
    unittest.main()
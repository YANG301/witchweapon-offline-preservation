import json
import unittest

import patch_embedded_asset_version as version


class EmbeddedAssetVersionTests(unittest.TestCase):
    def test_only_three_local_fixture_responses_change(self):
        payload = {route: {"body": "2.0.1.20043076\r\n"}
                   for route in version.VERSION_ROUTES}
        payload["/health"] = {"body": "ok"}
        source = {
            version.VERSION_MEMBER: b"2.0.1.20043076\r\n",
            version.FIXTURE_MEMBER: json.dumps(payload).encode("utf-8"),
        }
        changed = version.replacements(source.__getitem__)
        self.assertEqual(changed[version.VERSION_MEMBER], b"2.0.1.20043077\r\n")
        result = json.loads(changed[version.FIXTURE_MEMBER])
        self.assertEqual(result["/health"], payload["/health"])
        self.assertEqual(set(result), set(payload))

    def test_refuses_unknown_version(self):
        with self.assertRaises(ValueError):
            version.replacements(lambda _: b"unexpected")


if __name__ == "__main__":
    unittest.main()

"""Advance the embedded asset version so an APK upgrade reloads its bundles.

Unity keeps an asset index under the app's persistent-data directory.  If an
updated APK advertises the same version, that index survives `adb install -r`
and can leave the prior resource state in use.  Keep the APK version and its
private loopback fixture in lockstep; this never changes the public server.
"""

from __future__ import annotations

import json


VERSION_MEMBER = "assets/m.version"
FIXTURE_MEMBER = "assets/offline_responses.json"
OLD_VERSION = b"2.0.1.20043076"
NEW_VERSION = b"2.0.1.20043077"
VERSION_ROUTES = ("/getversion", "/m.version", "//getversion")


def replacements(read_member):
    version = read_member(VERSION_MEMBER)
    if version != OLD_VERSION + b"\r\n":
        raise ValueError("Unexpected embedded asset version")

    fixture = read_member(FIXTURE_MEMBER)
    if fixture.count(OLD_VERSION) != len(VERSION_ROUTES):
        raise ValueError("Unexpected asset version fixture count")
    decoded = json.loads(fixture)
    for route in VERSION_ROUTES:
        if decoded[route]["body"] != (OLD_VERSION + b"\r\n").decode("ascii"):
            raise ValueError("Unexpected fixture response at " + route)

    updated_fixture = fixture.replace(OLD_VERSION, NEW_VERSION)
    updated = json.loads(updated_fixture)
    for route in VERSION_ROUTES:
        if updated[route]["body"] != (NEW_VERSION + b"\r\n").decode("ascii"):
            raise ValueError("Fixture version did not update at " + route)
    return {
        VERSION_MEMBER: NEW_VERSION + b"\r\n",
        FIXTURE_MEMBER: updated_fixture,
    }

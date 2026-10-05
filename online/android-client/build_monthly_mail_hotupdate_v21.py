"""Sign monthly-card and inbox refresh as sequence 21."""

import build_gift_contents_hotupdate_v20 as previous


previous.builder.PREVIOUS = (
    "20-cce0c40dfaa16f17ab2835613aca89c559632528045a807e205a55d231464294")
previous.builder.SEQUENCE = 21
previous.builder.NEW_LUA = (
    "a6431c1e803c2dfc359f12e64f3e35528cc4b8ea5df90c1c175125d32471404d")
previous.builder.ASSETS = dict(previous.builder.ASSETS)
previous.builder.ASSETS["assetbundle/lua/lua.ab"] = previous.builder.NEW_LUA


if __name__ == "__main__":
    print("MONTHLY_MAIL_HOTUPDATE_V21_CANDIDATE_OK", previous.builder.build())

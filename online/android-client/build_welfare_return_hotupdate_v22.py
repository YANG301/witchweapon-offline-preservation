"""Sign the original welfare-return UI repair as sequence 22."""

import build_monthly_mail_hotupdate_v21 as previous


builder = previous.previous.builder
builder.PREVIOUS = (
    "21-0341ff612ac5167519c632b0b8d5803f9266f94712d81f95eb738eccb9aa2eee")
builder.SEQUENCE = 22
builder.ASSETS = dict(builder.ASSETS)
builder.ASSETS["assetbundle/lua/lua_projx_ui.ab"] = (
    "3654dbe119b72f1c5a0a2b86b581edc81ba7b84a13bfe85d63cfe1c078c40f61")


if __name__ == "__main__":
    print("WELFARE_RETURN_HOTUPDATE_V22_CANDIDATE_OK", builder.build())

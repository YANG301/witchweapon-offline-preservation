"""Restore the original icon/name/quantity rows in all seven public gifts."""

import build_gift_detail_hotupdate_v19 as builder


builder.PREVIOUS = "19-c7169ae76261a7bd1779267bb55cd12cd6810ce2634a941652c42528f7d9c4ba"
builder.SEQUENCE = 20
builder.NEW_LUA = "7eedd74aa0e7306864a44fbe405f087d8c2cc709e9aa8ea13014c1656ae38a05"
builder.ASSETS = dict(builder.ASSETS)
builder.ASSETS["assetbundle/lua/lua.ab"] = builder.NEW_LUA
builder.ASSETS["assetbundle/config/clientexel/item.ab"] = (
    "cb0fc7196a97924bbdb6d5c83146053fe48034993d2788a12ca6ec12bce56210")


if __name__ == "__main__":
    print("GIFT_CONTENTS_HOTUPDATE_V20_CANDIDATE_OK", builder.build())

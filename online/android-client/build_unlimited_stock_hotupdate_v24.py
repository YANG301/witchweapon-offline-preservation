"""Sign the unlimited-stock badge repair as sequence 24."""

import build_resource_shop_hotupdate_v23 as previous


builder = previous.builder
builder.PREVIOUS = (
    "23-7ea4daada30603a5027a7c799bc4f1b60b677a4b6d5c530bbd267e1040396091")
builder.SEQUENCE = 24
builder.ASSETS = dict(builder.ASSETS)
builder.ASSETS["assetbundle/lua/lua.ab"] = (
    "41687e77660680325c7c306509bfeeac20f62abb5f56750609e0369076156b94")


if __name__ == "__main__":
    print("UNLIMITED_STOCK_HOTUPDATE_V24_CANDIDATE_OK", builder.build())

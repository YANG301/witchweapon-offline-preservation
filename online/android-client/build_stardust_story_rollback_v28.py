"""Pre-sign the stable v24 content as a monotonic v28 rollback release."""

import build_unlimited_stock_hotupdate_v24 as previous


builder = previous.builder
builder.PREVIOUS = (
    "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023")
builder.SEQUENCE = 28
builder.ASSETS = dict(builder.ASSETS)


if __name__ == "__main__":
    print("STARDUST_ROLLBACK_V28_READY", builder.build())

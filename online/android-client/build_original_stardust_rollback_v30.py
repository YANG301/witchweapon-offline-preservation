"""Pre-sign the stable resource state as a monotonic sequence-30 rollback."""

import build_unlimited_stock_hotupdate_v24 as previous


builder = previous.builder
builder.PREVIOUS = "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023"
builder.SEQUENCE = 30
builder.ASSETS = dict(builder.ASSETS)


if __name__ == "__main__":
    print("ORIGINAL_STARDUST_ROLLBACK_V30_READY", builder.build())

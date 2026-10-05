"""Sign the reviewed resource-shop layout and navigation as sequence 23."""

import build_welfare_return_hotupdate_v22 as previous


builder = previous.builder
builder.PREVIOUS = (
    "22-79a0d70860f308f831a6f9920303a639ccf7ccf0e131604b24d9ab02db49be3d")
builder.SEQUENCE = 23
builder.ASSETS = dict(builder.ASSETS)
builder.ASSETS.update({
    "assetbundle/config/clientexel/shopbigset.ab":
        "d75a5514856c147016120df460046d33b8b5ca213e16762168dd99098ed052c5",
    "assetbundle/config/clientexel/shop.ab":
        "8f74afe74ae5633dc0592358abd3133cc64ed2ca369501d884e64cf07683a06c",
    "assetbundle/lua/lua.ab":
        "4255fb381513e113a6ab2a0e1ae7482f7614e6a7a02437bd17382b9ee1e84271",
    "assetbundle/assets/resources/ui/prefab/shop/newshoppanel.ab":
        "e7482aaabd7f9d304694490e19f95e28ebf69e634c54cf645d568df0b396a408",
})


if __name__ == "__main__":
    print("RESOURCE_SHOP_HOTUPDATE_V23_CANDIDATE_OK", builder.build())

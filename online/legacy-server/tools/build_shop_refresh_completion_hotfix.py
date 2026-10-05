"""Preserve original completion support on the last allowed manual refresh."""
import build_shop_refresh_protocol_hotfix as build

build.BASE_SHA='7d08be9ef5a9137667dcc31c643b85521050bd0db43855a4fe5f0112a70e68cd'
build.OUTPUT=build.ROOT/'build/witchweapon-legacy-shop-refresh-completion.jar'
build.TEMP=build.Path(r'D:\Environment\Java\temp\witch-shop-refresh-completion')
build.REGRESSION_MESSAGE='Last successful refresh must preserve native completion support flag'

if __name__=='__main__':build.main()

"""Build a signed Lua-only star-shop patch from an explicit base snapshot."""
import argparse
import build_star_shop_hotupdate_v79 as build
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True)
    parser.add_argument('--sequence',required=True,type=int)
    parser.add_argument('--rollback-base')
    args=parser.parse_args();build.BASE=args.base;build.main(sequence=args.sequence,rollback_base=args.rollback_base)

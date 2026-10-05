"""Record original permanent weapon duplicate materials for prayer exchanges."""
import csv
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path(r'D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel')

def main():
    source=(ROOT/'src/com/codex/witchweapon/NormalDrawRates.java').read_text(encoding='utf-8')
    block=re.search(r'WEAPONS=\{(.*?)\n    \};',source,re.S).group(1)
    groups=[[int(x) for x in re.findall(r'(\d+)L',part)] for part in re.findall(r'\{([^{}]+)\}',block)]
    assert list(map(len,groups))==[15,29,16]
    catalog=json.loads((ROOT/'resources/offline_responses.json').read_text(encoding='utf-8'))['_catalog']
    with (ORIGINAL/'servantweapon.txt').open(encoding='utf-8-sig',newline='') as stream:
        rows={}
        for row in csv.DictReader(stream):
            if not row['ID'].isdigit() or row['channel_group'] not in ('0','22'):continue
            rows[int(row['ID'])]=row
    decomposition={}
    for rarity,group in zip((4,3,2),groups):
        for weapon in group:
            row=rows[weapon]
            assert int(row['weapon_rare'])==rarity==catalog['weapons'][str(weapon)]['rare']
            rewards=[]
            for i in range(1,4):
                item=int(row['decompose_item_id'+str(i)] or '0')
                amount=int(row['decompose_item_num'+str(i)] or '0')
                if item and amount:
                    assert str(item) in catalog['items'] and amount>0
                    rewards.append([item,amount])
            stone=int(row['knife_stone_id'] or '0');amount=int(row['knife_stone_num'] or '0')
            assert str(stone) in catalog['items'] and amount>0
            decomposition[str(weapon)]={'materials':rewards,'knifeStone':[stone,amount]}
    assert len(decomposition)==60
    pieces={}
    with (ORIGINAL/'servant.txt').open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            if row['ID'] not in catalog['servants'] or row['channel_group'] not in ('0','22'):continue
            item=int(row['item_id']);assert str(item) in catalog['items']
            pieces[row['ID']]=item
    assert set(pieces)==set(catalog['servants'])
    with (ORIGINAL/'constant.txt').open(encoding='utf-8-sig',newline='') as stream:
        constants=list(csv.DictReader(stream))
    fragment_counts={}
    for rarity,label in ((2,'R'),(3,'SR'),(4,'SSR')):
        row=next(row for row in constants if row['ID']=='SERVANT_PIECE_WITH_WEAPON_'+label)
        # The value column in the original Constant table is its fourth field.
        fragment_counts[str(rarity)]=int(list(row.values())[3])
    assert fragment_counts=={'2':2,'3':20,'4':100}
    result={'schemaVersion':1,'source':'CN permanent Sothos publicity pool; original servantweapon.txt duplicate materials',
        'decomposition':decomposition,'servantPieces':pieces,'fragmentCounts':fragment_counts}
    target=ROOT/'resources/prayer_shop_catalog.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert json.loads(target.read_text(encoding='utf-8'))==result
    print('PRAYER_ORIGINAL_MATERIALS_VERIFIED weapons=60',flush=True)

if __name__=='__main__':main()

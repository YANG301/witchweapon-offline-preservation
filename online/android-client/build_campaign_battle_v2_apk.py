"""Build campaign fixes with a bounded, read-only battle/guide diagnostic."""
import argparse
import json
import zipfile
from pathlib import Path

import build_original_campaign_apk as campaign
import patch_original_campaign as asset
from build_online_apk import patch_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    import patch_campaign_battle_probe as probe
    replacements = campaign.prepare()
    member = 'assets/assetbundle/lua/lua.ab'
    replacements[member] = asset.patch_asset(replacements[member], 'init.lua', probe.patch)
    with zipfile.ZipFile(campaign.SOURCE) as source:
        replacements[campaign.INDEX] = patch_index(source.read(campaign.INDEX), {
            '/' + name[len('assets/assetbundle/'):]: data
            for name, data in replacements.items() if name.startswith('assets/assetbundle/')})
    if not args.build:
        print('CAMPAIGN_BATTLE_V2_PATCH_CHECK_OK', len(replacements))
        return
    campaign.RESULT = campaign.HERE / 'build/witchweapon-online-original-ui-campaign-battle-v2.apk'
    campaign.REPORT = campaign.HERE / 'build/主线战斗暂停排查候选包验收.json'
    campaign.TEMP = Path(r'D:\Environment\Android\temp\witch-online-campaign-restore')
    report = campaign.build(replacements)
    report['readOnlyBattleGuideProbe'] = True
    report['runtimeValidated'] = False
    campaign.REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('CAMPAIGN_BATTLE_V2_APK_READY', report['testApk']['sha256'])


if __name__ == '__main__':
    main()

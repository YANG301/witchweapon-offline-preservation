"""Build the user-requested temporary simple campaign with original game controls."""
import argparse
import json
import zipfile

import build_original_campaign_apk as campaign
import patch_simple_campaign as simple
from patch_chapter_level_up_duplicates import patch_level_up_dictionary
from build_online_apk import patch_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    replacements = campaign.prepare()
    prefix = 'assets/assetbundle/'
    moblist = prefix + 'config/clientexel/instancemoblist.ab'
    lesson = prefix + 'config/clientexel/lessontrigger.ab'
    replacements[moblist] = simple.patch_simple_moblist(replacements[moblist])
    with zipfile.ZipFile(campaign.SOURCE) as source:
        trigger = simple.patch_bundle(source.read(lesson))
        if trigger != source.read(lesson):
            replacements[lesson] = trigger
        for abi in ('armeabi-v7a', 'arm64-v8a'):
            name = 'lib/' + abi + '/libil2cpp.so'
            replacements[name], changed = patch_level_up_dictionary(source.read(name), abi)
            if changed != 19:
                raise ValueError('Unexpected native level-up baseline')
        replacements[campaign.INDEX] = patch_index(source.read(campaign.INDEX), {
            '/' + name[len(prefix):]: value for name, value in replacements.items()
            if name.startswith(prefix)})
    if not args.build:
        print('SIMPLE_CAMPAIGN_APK_CHECK_OK', len(replacements), 'payload members')
        return
    campaign.RESULT = campaign.HERE / 'build/witchweapon-online-original-ui-simple-campaign-v1.apk'
    campaign.REPORT = campaign.HERE / 'build/极简主线客户端验收.json'
    report = campaign.build(replacements)
    report.update(campaignProfile='simple-campaign-v1',
                  mainlineStageCount=235, scene='map_1010_classroomhallway',
                  layout='single-area-single-zone-single-wave-one-weak-enemy',
                  mainlineBattleLessons='already absent in pinned APK; verified unchanged',
                  changedUnityAssets=['init.lua', 'SelectLevelDetailPatch.lua',
                      'Instance:3110001003', 'InstanceMobList:235 mainline rows',
                      'Dictionary:1311000100301,1311000100302'],
                  chapter16MissingMobData='explicit temporary template, not original reconstruction',
                  removedReadOnlyBattleProbe=True, runtimeValidated=False)
    campaign.REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('SIMPLE_CAMPAIGN_APK_READY', report['testApk']['sha256'])


if __name__ == '__main__':
    main()

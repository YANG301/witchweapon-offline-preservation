"""Build a separate original-UI candidate with authenticated existing-role summary.

Do not distribute or install until /api/v1/legacy-role has been deployed and the
two known pre-metadata Java saves have been explicitly migrated and verified.
The v4-start APK remains an independent, working rollback candidate.
"""

import build_original_ui_apk as candidate


candidate.ROLE_SUMMARY = True
candidate.ADDED = candidate.ADDED | {candidate.ROLE_ASSET}
candidate.RESULT = candidate.base.OUTPUT / 'witchweapon-online-original-ui-role-test.apk'
candidate.REPORT = candidate.base.OUTPUT / '原版登录角色摘要候选包验收.json'


if __name__ == '__main__':
    candidate.main()

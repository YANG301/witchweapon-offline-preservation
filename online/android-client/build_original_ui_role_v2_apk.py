"""Build a separate original-UI role candidate with fresh cached-login role state.

The earlier role candidate and the working original-UI APK remain untouched.
Runtime validation still requires the deployed role endpoint and old-save migration.
"""

import build_original_ui_apk as candidate


candidate.ROLE_SUMMARY = True
candidate.ADDED = candidate.ADDED | {candidate.ROLE_ASSET}
candidate.RESULT = candidate.base.OUTPUT / 'witchweapon-online-original-ui-role-v2-test.apk'
candidate.REPORT = candidate.base.OUTPUT / '原版登录角色摘要候选包v2验收.json'


if __name__ == '__main__':
    candidate.main()

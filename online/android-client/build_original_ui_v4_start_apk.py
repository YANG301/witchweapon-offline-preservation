"""Original Unity login startup probe fix; keeps role-summary v4 gate off."""

import build_original_ui_apk as candidate


candidate.RESULT = candidate.base.OUTPUT / 'witchweapon-online-original-ui-v4-start-test.apk'
candidate.REPORT = candidate.base.OUTPUT / '原版登录首屏修复包验收.json'


if __name__ == '__main__':
    candidate.main()

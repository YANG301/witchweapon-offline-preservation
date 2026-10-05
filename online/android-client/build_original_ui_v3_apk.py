"""Build the next isolated original-login test APK without replacing v2."""

from pathlib import Path

import build_original_ui_apk as candidate


candidate.RESULT = candidate.base.OUTPUT / 'witchweapon-online-original-ui-v3-test.apk'
candidate.REPORT = candidate.base.OUTPUT / '原版登录候选包v3验收.json'


if __name__ == '__main__':
    candidate.main()

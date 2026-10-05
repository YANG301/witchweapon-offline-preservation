"""Build a separate startup-only diagnostic APK; never replace validated APKs."""

import build_original_ui_apk as candidate


candidate.RESULT = candidate.base.OUTPUT / 'witchweapon-online-original-ui-diagnostic.apk'
candidate.REPORT = candidate.base.OUTPUT / '原版登录首屏诊断包验收.json'
candidate.DIAGNOSTIC = True
candidate.ADDED = candidate.ADDED | {candidate.DIAGNOSTIC_ASSET}


if __name__ == '__main__':
    candidate.main()

"""Separate emulator-only original UI form diagnostic package.

Preserves the verified v4-start and fallback APKs. This candidate logs only
fixed stage/error categories, media class, known-field bitmask and key counts.
It must be removed after the original form incompatibility is diagnosed.
"""

import build_original_ui_apk as candidate


candidate.AUTH_DIAGNOSTIC = True
candidate.ADDED = candidate.ADDED | {candidate.AUTH_DIAG_ASSET}
candidate.RESULT = candidate.base.OUTPUT / 'witchweapon-online-original-ui-auth-diagnostic.apk'
candidate.REPORT = candidate.base.OUTPUT / '原版登录表单诊断包验收.json'


if __name__ == '__main__':
    candidate.main()

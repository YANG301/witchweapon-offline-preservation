"""Build the original-UI saved-login candidate without replacing prior APKs.

It retains the role-v2 package name so Android preserves the existing Unity
account cache across an upgrade. The previous signed APK and report remain
available for rollback.
"""

import build_original_ui_role_v2_apk  # Enables the authenticated role summary.
import build_original_ui_apk as candidate


candidate.RESULT = candidate.base.OUTPUT / 'witchweapon-online-original-ui-remember-v1-test.apk'
candidate.REPORT = candidate.base.OUTPUT / '原版登录免密回登候选包验收.json'
candidate.INTERMEDIATE_STEM = 'original-ui-remember-v1'

compile_role_candidate = candidate.compile_candidate


def compile_remember_candidate(source_files, old_classes):
    dex, classes = compile_role_candidate(source_files, old_classes)
    required = {
        'Lcom/codex/witchweapon/OnlineAuthTokens;',
        'Lcom/codex/witchweapon/OnlineSessionStore;',
    }
    if not required.issubset(classes):
        raise ValueError('Compiled candidate lacks saved-login support')
    return dex, classes


candidate.compile_candidate = compile_remember_candidate


if __name__ == '__main__':
    candidate.main()

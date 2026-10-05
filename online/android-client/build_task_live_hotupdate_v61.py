"""Task live sync and native reward normalization with original ToLua binding."""
import build_task_live_hotupdate_v59 as previous
build = previous.build
build.SEQUENCE = 61
build.ROLLBACK_SEQUENCE = 62

if __name__ == '__main__':
    build.main()

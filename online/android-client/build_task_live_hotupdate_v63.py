"""Refresh active mainline tasks and fetch successors after native claims."""
import build_task_live_hotupdate_v61 as previous
build = previous.build
build.SEQUENCE = 63
build.ROLLBACK_SEQUENCE = 64

if __name__ == '__main__':
    build.main()

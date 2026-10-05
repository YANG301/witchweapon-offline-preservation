"""Repair task initialization and duplicated native Guild reward display."""
import build_task_live_hotupdate_v57 as build

build.SEQUENCE = 59
build.ROLLBACK_SEQUENCE = 60
build.SOURCES = (build.SOURCE, build.SOURCE.with_name('init-task-loot-display.lua'))

if __name__ == '__main__':
    build.main()

"""Append-only, player-facing release notes shared by notices and full APKs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
HISTORY = PROJECT / 'legacy-server/resources/player_update_history.json'
FIXTURE = PROJECT / 'legacy-server/resources/offline_responses.json'
ROUTE = '/Notice/gameContent'


def validate(records):
    assert isinstance(records, list) and records
    sequences = [row['sequence'] for row in records]
    assert all(type(value) is int and value > 0 for value in sequences)
    assert sequences == sorted(set(sequences))
    for row in records:
        assert set(row) == {'sequence', 'notes'}
        assert isinstance(row['notes'], list) and 1 <= len(row['notes']) <= 3
        assert all(isinstance(note, str) and note == note.strip()
                   and 0 < len(note) <= 80 and '\n' not in note and '\r' not in note
                   for note in row['notes'])
    return records


def pending(sequence, notes=()):
    records = validate(json.loads(HISTORY.read_text(encoding='utf-8')))
    if records[-1]['sequence'] == sequence:
        assert not notes or records[-1]['notes'] == list(notes), 'Do not overwrite published notes'
    else:
        assert sequence > records[-1]['sequence'], 'Release notes must be appended in order'
        assert notes, 'Supply --note with a short player-facing change for each release'
        records = records + [dict(sequence=sequence, notes=list(notes))]
    return validate(records)


def render(records):
    validate(records)
    sections = [f"第{row['sequence']}版\n" + '\n'.join('· ' + note for note in row['notes'])
                for row in reversed(records)]
    return '更新记录\n\n' + '\n\n'.join(sections)


def sync(records):
    validate(records)
    original = json.loads(FIXTURE.read_text(encoding='utf-8'))
    candidate = json.loads(json.dumps(original))
    notices = json.loads(candidate[ROUTE]['body'])
    update, = [row for row in notices if row['ID'] == 5]
    assert update['Title'] == '更新内容与问题修复'
    update['Content'] = render(records)
    candidate[ROUTE]['body'] = json.dumps(notices, ensure_ascii=False, separators=(',', ':'))
    assert {key for key in original if candidate[key] != original[key]} <= {ROUTE}
    HISTORY.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    FIXTURE.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert json.loads(HISTORY.read_text(encoding='utf-8')) == records
    assert json.loads(FIXTURE.read_text(encoding='utf-8')) == candidate


def check(sequence):
    records = pending(sequence)
    notices = json.loads(json.loads(FIXTURE.read_text(encoding='utf-8'))[ROUTE]['body'])
    update, = [row for row in notices if row['ID'] == 5]
    assert update['Content'] == render(records), 'Announcement must contain the complete release history'
    return len(records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sequence', type=int, required=True)
    parser.add_argument('--note', action='append', default=[])
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        print('NOTICE_HISTORY_VERIFIED', check(args.sequence))
    else:
        records = pending(args.sequence, args.note)
        sync(records)
        print('NOTICE_HISTORY_APPENDED', args.sequence, len(records))

"""Read-only checks for the source review tree; no deployment or game access."""
from pathlib import Path
from urllib.parse import unquote
import argparse
import ast
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect():
    errors = []
    manifest = json.loads((ROOT / 'docs/source-manifest.json').read_text(encoding='utf-8'))
    counts = {'preservedBaselineFiles': 0, 'copiedSourceFiles': 0,
              'pythonFiles': 0, 'jsonFiles': 0, 'markdownFiles': 0, 'localLinks': 0}
    for label, expected_key, counter in (('baseline', 'sha256', 'preservedBaselineFiles'),
                                         ('files', 'exportSHA256', 'copiedSourceFiles')):
        for record in manifest[label]:
            path = ROOT / record['path']
            if not path.is_relative_to(ROOT) or not path.is_file():
                errors.append('Missing tracked source: ' + record['path'])
            elif sha256(path) != record[expected_key]:
                canonical = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                if label != 'baseline' or canonical != record.get('canonicalSHA256'):
                    errors.append('Source hash changed: ' + record['path'])
            counts[counter] += 1

    prohibited_extensions = {'.apk', '.apks', '.aab', '.ab', '.exe', '.dll', '.jar',
                             '.class', '.dex', '.pyc', '.pyo', '.pem', '.key', '.p12',
                             '.pfx', '.jks', '.keystore', '.zip', '.7z', '.log'}
    prohibited_directories = {'.local', '__pycache__', '.venv', 'node_modules', 'Library'}
    private_key = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')
    personal_email = re.compile(r'(?i)[A-Za-z0-9_.+-]+@(?:qq|outlook|hotmail)\.com')
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if '.git' in relative.parts:
            continue
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            errors.append('Linked entry: ' + relative.as_posix())
            continue
        if path.is_dir():
            if path.name in prohibited_directories:
                errors.append('Excluded directory present: ' + relative.as_posix())
            continue
        if path.suffix.lower() in prohibited_extensions or path.name == 'offline_save_v1.json':
            errors.append('Excluded file present: ' + relative.as_posix())
        try:
            text = path.read_text(encoding='utf-8-sig')
        except UnicodeError:
            errors.append('Non-UTF8 source: ' + relative.as_posix())
            continue
        if '\ufffd' in text:
            errors.append('Replacement character: ' + relative.as_posix())
        if private_key.search(text):
            errors.append('Private key material: ' + relative.as_posix())
        if personal_email.search(text):
            errors.append('Personal mailbox literal: ' + relative.as_posix())
        if path.suffix == '.py':
            counts['pythonFiles'] += 1
            try:
                ast.parse(text, str(path))
            except SyntaxError as error:
                errors.append('Python syntax: ' + relative.as_posix() + ':' + str(error.lineno))
        if path.suffix == '.json':
            counts['jsonFiles'] += 1
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                errors.append('JSON syntax: ' + relative.as_posix() + ':' + str(error.lineno))
        if path.suffix == '.md':
            counts['markdownFiles'] += 1
            # Inline local links, including the new review documentation.
            for raw in re.findall(r'!?\[[^\]\n]*\]\(([^\n)]+)\)', text):
                target = raw.strip().split(' "', 1)[0].strip('<>')
                if not target or target.startswith('#') or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
                    continue
                counts['localLinks'] += 1
                candidate = (path.parent / unquote(target.split('#', 1)[0])).resolve()
                if not candidate.is_relative_to(ROOT) or not candidate.exists():
                    errors.append('Broken local link: ' + relative.as_posix() + ' -> ' + target)
    stable = ROOT / 'online/legacy-server/src/com/codex/witchweapon/LocalSave.java'
    if 'StoneSlateBattle' in stable.read_text(encoding='utf-8'):
        errors.append('Experimental stone-slate hooks in stable source')
    if (stable.parent / 'StoneSlateBattle.java').exists():
        errors.append('Experimental stone-slate class in stable source')
    store = (ROOT / 'online/server/store.go').read_text(encoding='utf-8')
    if 'const ownerPublicRIDAccount = "OwnerReviewAccount00001"' not in store:
        errors.append('Public owner identity placeholder missing')
    return {'schemaVersion': 1, 'passed': not errors, 'checks': counts, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Optional UTF-8 JSON report inside this tree')
    args = parser.parse_args()
    result = inspect()
    if args.report:
        output = args.report.resolve()
        if not output.is_relative_to(ROOT) or output.suffix != '.json':
            raise ValueError('Report path must be a JSON file inside this review tree')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())

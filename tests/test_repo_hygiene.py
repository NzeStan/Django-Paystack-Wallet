"""Guard against committing anything shaped like a real credential."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Real Paystack keys: sk_/pk_ + test/live + 40 hex characters
PAYSTACK_KEY = re.compile(r'\b(sk|pk)_(test|live)_[0-9a-fA-F]{40}\b')


def tracked_files():
    try:
        output = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip('not a git checkout')
    return [ROOT / name for name in output.splitlines()]


def test_no_paystack_keys_in_repository():
    offenders = []
    for path in tracked_files():
        if not path.is_file() or path.suffix in {'.png', '.jpg', '.ico', '.pyc', '.sqlite3'}:
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        offenders += [f"{path.relative_to(ROOT)}: {m.group(0)[:12]}..." for m in PAYSTACK_KEY.finditer(text)]
    assert offenders == [], f"Key-shaped strings found (use obviously fake values): {offenders}"


# Hard-coded passwords/secrets in code, e.g. password='hunter2', set_password('x'), 'password1': 'x'
PASSWORD_LITERAL = re.compile(
    r"""(?ix)
    (?:password\w*|passwd|secret_key|api_key|secret)['"]?\s*[:=]\s*['"][^'"\s]{3,}['"]
    | set_password\(\s*['"][^'"]+['"]
    """
)


def test_no_hardcoded_passwords_in_code():
    """Generate test/demo credentials at runtime instead (django.utils.crypto.get_random_string)."""
    offenders = []
    for path in tracked_files():
        if path.suffix != '.py' or not path.is_file() or 'migrations' in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
            # Fake keys must contain the marker 'dummy-key-for-tests' so everyone can see they are fake
            if line.lstrip().startswith('#') or 'dummy-key-for-tests' in line:
                continue
            if PASSWORD_LITERAL.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:80]}")
    assert offenders == [], 'Hard-coded credentials found:\n' + '\n'.join(offenders)


def test_env_files_are_never_tracked():
    tracked = [p.name for p in tracked_files()]
    assert '.env' not in tracked
    assert 'db.sqlite3' not in tracked

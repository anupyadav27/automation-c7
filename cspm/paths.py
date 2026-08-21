"""
Where things live, resolved once.

Every module used to compute the output directory by counting `..` from its own
file. That works until a module moves. When `discovery/cli.py` became
`providers/aws/cli.py` it gained a directory level, so `../out` silently became
`providers/out` — a complete collection ran, reported success, and wrote 686
assets somewhere nothing else reads. Nothing failed; the numbers were simply
written to the wrong place.

The root is found by walking up for a marker rather than by counting, so moving
a module deeper or shallower changes nothing.
"""
import os

# Files that only ever exist at the top of this repository.
MARKERS = ('STRUCTURE.md', 'setup.py', '.git')


def repo_root(start=None):
    """The repository root, found by walking up from `start`."""
    path = os.path.abspath(start or __file__)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    while True:
        if any(os.path.exists(os.path.join(path, m)) for m in MARKERS):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            # Reached the filesystem root without a marker. Fall back to the
            # parent of this package rather than writing to '/'.
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = parent


ROOT = repo_root()
OUT = os.path.join(ROOT, 'out')
SAMPLES = os.path.join(OUT, 'samples')
UI_PUBLIC = os.path.join(ROOT, 'ui', 'public')
PROVIDERS = os.path.join(ROOT, 'providers')
AWS_CATALOG = os.path.join(PROVIDERS, 'aws', 'catalog')
POLICIES = os.path.join(ROOT, 'engines', 'compliance', 'policies')
POSTURE_CATALOG = os.path.join(ROOT, 'posture', 'catalog')


def ensure(path):
    os.makedirs(path, exist_ok=True)
    return path

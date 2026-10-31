"""Export/check the API contract without writing a development database."""
import argparse
import json
import tempfile
from pathlib import Path

from posify.app import create_app

parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
with tempfile.TemporaryDirectory() as tmp:
    contract = create_app(str(Path(tmp) / 'contract.db'), 'contract-export-only').openapi()
content = json.dumps(contract, indent=2, sort_keys=True) + '\n'
path = Path(__file__).resolve().parents[1] / 'packages/contracts/openapi.json'
if args.check:
    if not path.exists() or path.read_text() != content:
        raise SystemExit('Contract is stale. Run python scripts/export_contracts.py')
    print('OpenAPI contract matches implementation')
else:
    path.write_text(content)
    print('Updated packages/contracts/openapi.json')

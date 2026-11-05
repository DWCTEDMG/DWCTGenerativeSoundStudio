"""Create a versioned infrastructure-only candidate package, excluding state and secrets."""
import json
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[3]
deployment = root / 'deployment/ibm-cloud'
out = deployment / 'dist'
out.mkdir(exist_ok=True)
manifest = json.loads((root / 'ibm_catalog.json').read_text(encoding='utf-8'))
version = manifest['products'][0]['version']
prefix = f'edmg-ibm-{version}'
archive = out / f'{prefix}-candidate.tar.gz'
allowed = {'.tf', '.md', '.py', '.tftpl', '.example'}
files = [root / 'ibm_catalog.json', deployment / 'ibm_catalog.json', deployment / '.terraform.lock.hcl']
files += [p for p in deployment.rglob('*') if p.is_file() and p.suffix in allowed
          and not any(part in {'.terraform', 'dist'} for part in p.relative_to(deployment).parts)]
with tarfile.open(archive, 'w:gz') as tar:
    for path in sorted(set(files)):
        tar.add(path, arcname=prefix + '/' + path.relative_to(root).as_posix())
with tarfile.open(archive) as tar:
    names = tar.getnames()
    assert f'{prefix}/ibm_catalog.json' in names
    assert f'{prefix}/deployment/ibm-cloud/main.tf' in names
print(archive)

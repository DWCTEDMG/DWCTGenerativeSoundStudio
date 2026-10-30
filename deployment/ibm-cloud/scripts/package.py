"""Create an infrastructure-only candidate package, excluding state and secrets."""
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[3]
deployment = root / 'deployment/ibm-cloud'
out = deployment / 'dist'
out.mkdir(exist_ok=True)
archive = out / 'edmg-ibm-1.0.0-candidate.tar.gz'
allowed = {'.tf', '.md', '.py', '.tftpl', '.example'}
files = [root / 'ibm_catalog.json', deployment / 'ibm_catalog.json', deployment / '.terraform.lock.hcl']
files += [p for p in deployment.rglob('*') if p.is_file() and p.suffix in allowed
          and not any(part in {'.terraform', 'dist'} for part in p.relative_to(deployment).parts)]
with tarfile.open(archive, 'w:gz') as tar:
    for path in sorted(set(files)):
        tar.add(path, arcname='edmg-ibm-1.0.0/' + path.relative_to(root).as_posix())
with tarfile.open(archive) as tar:
    names = tar.getnames()
    assert 'edmg-ibm-1.0.0/ibm_catalog.json' in names
    assert 'edmg-ibm-1.0.0/deployment/ibm-cloud/main.tf' in names
print(archive)

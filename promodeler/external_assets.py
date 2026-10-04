"""Resolve user-supplied 3D references without copying source downloads into the repo."""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

from .build import find_blender
from .core import ModelingError

CATALOG = Path(__file__).resolve().parents[1] / 'assets' / 'external_references.json'
SCHEMA = 'promodeler-external-references/1.0'


def entries(catalog: str | Path = CATALOG) -> list[dict]:
    data = json.loads(Path(catalog).read_text(encoding='utf-8'))
    if data.get('schema') != SCHEMA or not isinstance(data.get('entries'), list):
        raise ModelingError('external.schema', f'Expected {SCHEMA}: {catalog}')
    rows = data['entries']
    ids = [row.get('id') for row in rows]
    if any(not isinstance(id, str) or not id for id in ids) or len(ids) != len(set(ids)):
        raise ModelingError('external.id', 'External asset IDs must be unique, nonempty strings.')
    return rows


def resolve(asset_id: str, catalog: str | Path = CATALOG) -> dict:
    item = next((row for row in entries(catalog) if row['id'] == asset_id), None)
    if item is None:
        raise ModelingError('external.id', f'Unknown external asset: {asset_id}')
    return item


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(4 * 1024 ** 2), b''):
            h.update(block)
    return h.hexdigest()


def verify(item: dict) -> Path:
    path = Path(item['sourceModel'])
    if not path.is_file():
        raise ModelingError('external.missing', f'Source model missing: {path}')
    if path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']:
        raise ModelingError('external.changed', f'Source differs from catalog receipt: {path}')
    return path


def validate_glb(path: Path) -> dict:
    """Check the GLB container and JSON scene before reporting an export."""
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ModelingError('external.glb', f'Truncated GLB: {path}')
        magic, version, declared_bytes = struct.unpack('<4sII', header)
        if magic != b'glTF' or version != 2 or declared_bytes != path.stat().st_size:
            raise ModelingError('external.glb', f'Invalid GLB header or length: {path}')
        chunk = stream.read(8)
        if len(chunk) != 8:
            raise ModelingError('external.glb', f'Missing GLB JSON chunk: {path}')
        length, kind = struct.unpack('<I4s', chunk)
        if kind != b'JSON' or length <= 0 or length > declared_bytes - 20:
            raise ModelingError('external.glb', f'Invalid GLB JSON chunk: {path}')
        document = json.loads(stream.read(length))
    if not document.get('meshes'):
        raise ModelingError('external.glb', f'GLB has no meshes: {path}')
    return {'meshes': len(document['meshes']), 'images': len(document.get('images', []))}


def export(asset_id: str, output: str | Path, *, catalog: str | Path = CATALOG) -> dict:
    """Export a catalogued prop or reference scene to a standalone GLB."""
    item = resolve(asset_id, catalog)
    if item['role'] not in ('reference_prop', 'reference_scene', 'reference_vegetation'):
        raise ModelingError('external.role', f'{asset_id} is a character or fitted module; use its canonical recipe.')
    source = verify(item)
    output = Path(output).resolve()
    if output.suffix.lower() != '.glb':
        raise ModelingError('external.output', 'Output path must end in .glb')
    if output.exists():
        raise ModelingError('external.output', f'Output already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == '.glb':
        shutil.copyfile(source, output)
        glb_contents = validate_glb(output)
        report = {'asset': asset_id, 'status': 'ok', 'source': str(source), 'sourceSha256': item['sha256'],
                  'glb': str(output), 'bytes': output.stat().st_size, 'sha256': sha256(output),
                  'textureStatus': 'source_glb_preserved', 'glbContents': glb_contents}
    else:
        blender = find_blender()
        script = Path(__file__).with_name('external_blender.py')
        receipt = output.with_suffix('.build.json')
        log = output.with_suffix('.blender.log')
        command = [blender, '--background', '--factory-startup', '--disable-autoexec', '--python-exit-code', '1',
                   '--python', str(script), '--', str(source), str(output), str(receipt)]
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
        if not output.is_file() or not receipt.is_file():
            raise ModelingError('external.blender', f'Blender import/export failed; see {log}')
        glb_contents = validate_glb(output)
        report = json.loads(receipt.read_text(encoding='utf-8'))
        if report.get('bytes') != output.stat().st_size or report.get('glb') != str(output):
            raise ModelingError('external.blender', f'Blender receipt does not match GLB; see {log}')
        if process.returncode:
            report['status'] = 'warning'
            report['blenderExitCode'] = process.returncode
            report['exitWarning'] = 'Blender exited abnormally after writing a structurally valid GLB.'
        report['glbContents'] = glb_contents
        report.update({'asset': asset_id, 'sourceSha256': item['sha256'], 'sha256': sha256(output)})
    output.with_suffix('.build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report

#!/usr/bin/python3
"""Fetch the pinned official Chrome for Testing build for isolated checks only."""
import base64
import hashlib
import json
from pathlib import Path
import stat
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'integration/browser-runtime'


def main():
    metadata = json.loads((OUT/'source.json').read_text())
    url = metadata['url']
    assert url.startswith('https://storage.googleapis.com/chrome-for-testing-public/')
    archive = OUT/'chrome-linux64.zip'
    if not archive.exists():
        with urllib.request.urlopen(url, timeout=60) as response, archive.with_suffix('.part').open('wb') as stream:
            headers = dict(response.headers)
            while True:
                block = response.read(4*1024*1024)
                if not block: break
                stream.write(block)
        (OUT/'download-headers.json').write_text(json.dumps(headers, indent=2)+'\n')
        archive.with_suffix('.part').rename(archive)
    headers = {k.lower(): v for k,v in json.loads((OUT/'download-headers.json').read_text()).items()}
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with archive.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            sha.update(block); md5.update(block)
    hashes = dict(item.strip().split('=',1) for item in headers['x-goog-hash'].split(','))
    # GCS can send x-goog-hash twice; an ordinary header dict may retain only
    # CRC32C. Its single-part object ETag is also the published MD5.
    published_md5 = hashes.get('md5')
    if published_md5:
        assert base64.b64encode(md5.digest()).decode() == published_md5, 'Publisher MD5 mismatch'
    else:
        assert md5.hexdigest() == headers['etag'].strip('"'), 'Publisher ETag/MD5 mismatch'
        published_md5 = base64.b64encode(md5.digest()).decode()
    assert archive.stat().st_size == int(headers['content-length']), 'Truncated archive'
    if metadata.get('archive_sha256'):
        assert sha.hexdigest() == metadata['archive_sha256'], 'Pinned SHA256 mismatch'
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        for entry in package.infolist():
            assert entry.filename.startswith('chrome-linux64/')
            target = (OUT/entry.filename).resolve()
            assert OUT.resolve() in target.parents
            mode = entry.external_attr >> 16
            assert not stat.S_ISLNK(mode), 'Unexpected archive symlink'
            package.extract(entry, OUT)
            if target.is_file(): target.chmod(0o755 if mode & 0o111 else 0o644)
    metadata.update(archive_sha256=sha.hexdigest(), archive_bytes=archive.stat().st_size,
                    publisher_md5=published_md5, publisher_md5_verified=True,
                    binary_sha256=hashlib.sha256((OUT/'chrome-linux64/chrome').read_bytes()).hexdigest(),
                    executable='integration/browser-runtime/chrome-linux64/chrome',
                    product_dependency=False, sandbox='unchanged; no disabling flags or environment')
    (OUT/'source.json').write_text(json.dumps(metadata, indent=2)+'\n')
    archive.with_suffix('.zip.sha256').write_text(sha.hexdigest()+'  '+archive.name+'\n')
    print(json.dumps(metadata), flush=True)


if __name__ == '__main__': main()

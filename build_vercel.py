"""Publish only allowlisted frontend assets to Vercel's CDN."""
from pathlib import Path
import shutil

root=Path(__file__).resolve().parent
for source in (root/'static').rglob('*'):
    if not source.is_file() or source.is_symlink(): continue
    relative=source.relative_to(root/'static')
    if source.suffix.lower() not in {'.js','.css','.svg','.png','.ico','.webp'}: continue
    if any(part.startswith('.') for part in relative.parts): continue
    if len(relative.parts)>1 and relative.parts[0]!='js': continue
    destination=root/'public'/relative
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)

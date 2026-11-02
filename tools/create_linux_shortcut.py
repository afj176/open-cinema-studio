"""Generate a Linux desktop entry with paths for this checkout."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def quote(value):
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value.replace('\\', '\\\\') + '"'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/Open Cinema.desktop')
    args = parser.parse_args()
    shell = shutil.which('sh')
    if not shell:
        parser.error('Run this generator on Linux with sh installed.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('[Desktop Entry]\nType=Application\nName=Open Cinema\n'
                           'Comment=From story to screen with local AI\nTerminal=true\n'
                           f'Exec={quote(shell)} {quote(ROOT / "start-open-cinema.sh")}\n'
                           'Categories=AudioVideo;Graphics;\n', encoding='utf-8')
    args.output.chmod(0o755)
    print(args.output)

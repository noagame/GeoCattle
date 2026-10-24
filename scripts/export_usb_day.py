"""Exporta un dia del archivo USB, incluidas capturas pendientes de entrega."""
import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters.lora_usb import Archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day', type=date.fromisoformat,
                        default=datetime.now(ZoneInfo('America/Santiago')).date())
    parser.add_argument('--directory', type=Path, default=ROOT / '.runtime/capture')
    args = parser.parse_args()
    archive = Archive(args.directory)
    folder = args.directory / 'daily' / args.day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'telemetry.jsonl'
    temporary = target.with_suffix('.tmp')
    count = 0
    with archive.connection() as db, temporary.open('w', encoding='utf-8') as output:
        rows = db.execute('SELECT payload,status,backend_id,received_at FROM captures WHERE local_day=? ORDER BY id', (args.day.isoformat(),))
        for row in rows:
            output.write(json.dumps({'payload': json.loads(row['payload']),
                'delivery_status': row['status'], 'backend_id': row['backend_id'],
                'received_at': row['received_at']}, ensure_ascii=False, allow_nan=False) + '\n')
            count += 1
    os.replace(temporary, target)
    print(f'{count} lecturas exportadas: {target}')


if __name__ == '__main__': main()

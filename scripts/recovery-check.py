import base64
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    encoded = base64.b64encode((root / 'vendor/CatVTON/resource/demo/example/person/men/model_5.png').read_bytes()).decode()
    with httpx.Client(base_url='http://127.0.0.1:3000', timeout=30, trust_env=False) as client:
        response = client.post('/api/tryon', json={'person_image': encoded,
            'garment_id': 'black_graphic_tee', 'category': 'upper_body'})
        response.raise_for_status()
        job_id = response.json()['job_id']
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = client.get('/api/tryon/' + job_id).json()
            if job['status'] == 'running':
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Task never started')
        service = 'worker-gpu' + str(job['gpu_id'])
        print(f'Fault injection: killing {service} during {job_id}', flush=True)
        subprocess.run(['docker', 'compose', 'kill', '-s', 'SIGKILL', service], cwd=root, check=True)
        subprocess.run(['docker', 'compose', 'start', service], cwd=root, check=True)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = client.get('/api/tryon/' + job_id).json()
            if job['status'] in {'completed', 'failed'}:
                break
            time.sleep(.5)
        assert job['status'] == 'completed', job
        print('Crash recovery completed:', job, flush=True)
        session = uuid4().hex
        latest = None
        for sequence, garment in enumerate(['black_graphic_tee', 'brown_jersey', 'grey_cardigan'], 1):
            response = client.post('/api/tryon', json={'person_image': encoded,
                'garment_id': garment, 'category': 'upper_body', 'session_id': session, 'sequence': sequence})
            response.raise_for_status()
            latest = response.json()
        stale = client.post('/api/tryon', json={'person_image': encoded, 'garment_id': 'cream_vest',
            'category': 'upper_body', 'session_id': session, 'sequence': 2})
        assert stale.status_code == 409, stale.text
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            latest = client.get('/api/tryon/' + latest['job_id']).json()
            if latest['status'] in {'completed', 'failed'}:
                break
            time.sleep(.5)
        assert latest['status'] == 'completed', latest
        report = {'crash_recovery': job, 'latest_request': latest, 'stale_request_status': stale.status_code}
        (root / 'reports/recovery.json').write_text(json.dumps(report, indent=2))
        print('Latest request and out-of-order checks passed', flush=True)


if __name__ == '__main__':
    main()

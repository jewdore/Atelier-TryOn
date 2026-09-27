import argparse
import asyncio
import base64
import json
import statistics
import subprocess
import time
from pathlib import Path

import httpx


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def gpu_sample() -> list[dict]:
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=index,utilization.gpu,memory.used,memory.total',
            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5, check=True)
        return [dict(zip(['gpu_id', 'utilization_percent', 'memory_used_mib', 'memory_total_mib'],
                         map(float, line.split(',')))) for line in result.stdout.strip().splitlines()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


async def run(arguments: argparse.Namespace) -> None:
    encoded = base64.b64encode(Path(arguments.person).read_bytes()).decode() if not arguments.video else ''
    reports = []
    async with httpx.AsyncClient(base_url=arguments.url, timeout=40, trust_env=False,
            limits=httpx.Limits(max_connections=64)) as client:
        health = await client.get('/api/health')
        health.raise_for_status()
        inventory = (await client.get('/api/garments')).json()
        garment = next((item for item in inventory if item['id'] == arguments.garment), None) if arguments.garment else (inventory[0] if inventory else None)
        if not garment:
            raise RuntimeError('Garment not found or closet empty')
        mock = any(worker['model'] == 'mock' for worker in health.json()['workers'])
        if mock:
            print('WARNING: MOCK control-plane benchmark; NOT GPU inference performance')
        kind = 'video' if arguments.video else 'image'
        ready_workers = health.json().get(kind + '_workers', health.json()['ready_workers'])
        if arguments.require_workers and ready_workers != arguments.require_workers:
            raise RuntimeError('Required number of ready workers not present')
        video_id = None
        if arguments.video:
            response = await client.post('/api/videos', content=Path(arguments.video).read_bytes(),
                headers={'Content-Type': 'application/octet-stream'}, timeout=240)
            response.raise_for_status()
            video_id = response.json()['video_id']

        async def one() -> dict:
            started = time.perf_counter()
            payload = {'garment_id': garment['id'], 'category': garment['category']}
            payload.update({'video_id': video_id} if arguments.video else {'person_image': encoded})
            response = await client.post('/api/tryon/video' if arguments.video else '/api/tryon', json=payload)
            response.raise_for_status()
            job_id = response.json()['job_id']
            while time.perf_counter() - started < arguments.timeout:
                response = await client.get('/api/tryon/' + job_id)
                response.raise_for_status()
                job = response.json()
                if job['status'] == 'failed':
                    raise RuntimeError(f'{job_id}: {job.get("error")}')
                if job['status'] == 'completed':
                    result = await client.get(job['result_url'])
                    result.raise_for_status()
                    return {**job, 'end_to_end_ms': (time.perf_counter() - started) * 1000}
                await asyncio.sleep(0.1)
            raise TimeoutError(job_id)

        print('Concurrency  Success/Total   Avg ms   P50 ms   P95 ms   P99 ms    req/s  Queue ms')
        for concurrency in arguments.concurrency:
            samples = []
            sampling = True

            async def sample_loop() -> None:
                while sampling:
                    samples.append({'time': time.time(), 'gpus': await asyncio.to_thread(gpu_sample)})
                    await asyncio.sleep(0.5)

            sampler = asyncio.create_task(sample_loop())
            started = time.perf_counter()
            semaphore = asyncio.Semaphore(concurrency)

            async def limited() -> dict:
                async with semaphore:
                    return await one()

            outcomes = await asyncio.gather(*(limited() for _ in range(concurrency * arguments.rounds)), return_exceptions=True)
            elapsed = time.perf_counter() - started
            sampling = False
            await sampler
            successful = [item for item in outcomes if isinstance(item, dict)]
            errors = [str(item) for item in outcomes if isinstance(item, BaseException)]
            latencies = [item['end_to_end_ms'] for item in successful]
            queues = [item['timings']['queue_time_ms'] for item in successful]
            summary = {'concurrency': concurrency, 'successful': len(successful), 'total': len(outcomes),
                'elapsed_seconds': elapsed, 'throughput_rps': len(successful) / elapsed,
                'avg_ms': statistics.mean(latencies) if latencies else None,
                'p50_ms': percentile(latencies, .5) if latencies else None,
                'p95_ms': percentile(latencies, .95) if latencies else None,
                'p99_ms': percentile(latencies, .99) if latencies else None,
                'queue_avg_ms': statistics.mean(queues) if queues else None,
                'gpu_ids_used': sorted({item['gpu_id'] for item in successful}),
                'errors': errors, 'jobs': successful, 'gpu_samples': samples}
            reports.append(summary)
            if latencies:
                print(f'{concurrency:<12} {len(successful):>3}/{len(outcomes):<8} {summary["avg_ms"]:8.1f} {summary["p50_ms"]:8.1f} {summary["p95_ms"]:8.1f} {summary["p99_ms"]:8.1f} {summary["throughput_rps"]:8.2f} {summary["queue_avg_ms"]:9.1f}')
            else:
                print(f'{concurrency:<12} FAILED: {errors[:3]}')
        output = Path(arguments.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'mock': mock, 'kind': kind, 'health': health.json(), 'results': reports}, indent=2))
        print(f'Raw jobs, GPU samples and errors: {output}')
        if any(report['errors'] for report in reports):
            raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:3000')
    parser.add_argument('--person', default='vendor/CatVTON/resource/demo/example/person/men/model_5.png')
    parser.add_argument('--video', help='Upload this video once; benchmark CatV2TON instead of image inference')
    parser.add_argument('--garment', default='black_graphic_tee')
    parser.add_argument('--concurrency', nargs='+', type=int, default=[1, 2, 4, 8, 16])
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=420)
    parser.add_argument('--require-workers', type=int, default=8)
    parser.add_argument('--output', default='reports/benchmark.json')
    args = parser.parse_args()
    if args.rounds < 1 or min(args.concurrency) < 1:
        parser.error('rounds and concurrency must be positive')
    asyncio.run(run(args))

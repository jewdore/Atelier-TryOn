import os
import sys

from redis import Redis

redis = Redis.from_url(os.environ['REDIS_URL'], decode_responses=True, socket_timeout=3)
state = redis.hgetall('worker:' + os.environ['GPU_ID'] + ':status')
sys.exit(0 if state.get('status') in {'idle', 'busy'} else 1)

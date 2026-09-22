import argparse
import time

p = argparse.ArgumentParser()
p.add_argument('--crash-after', type=int, default=20)
args = p.parse_args()

print('Starting mock Minecraft server...', flush=True)
started = time.time()
i = 0
while True:
    i += 1
    uptime = int(time.time() - started)
    print(f'TPS=20.0 MSPT=48.2 players={i % 7} uptime={uptime}s', flush=True)
    time.sleep(1)
    if time.time() - started >= args.crash_after:
        print('ERROR: simulated crash for recovery test', flush=True)
        raise SystemExit(1)

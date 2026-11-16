import resource, subprocess, sys, time
cmd = sys.argv[1:]
t0 = time.time()
rc = subprocess.call(cmd)
wall = time.time() - t0
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
cpu = ru.ru_utime + ru.ru_stime
print(f"METER rc={rc} wall={wall:.1f}s cpu={cpu:.1f}s cores={cpu / max(wall, 1e-9):.2f} peak_rss={ru.ru_maxrss / 1024:.0f}MB", flush=True)
sys.exit(rc)

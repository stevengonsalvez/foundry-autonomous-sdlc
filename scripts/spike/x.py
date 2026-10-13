import sys, time
from common import sandbox
sb=sandbox(); t=time.time(); sb.ensure_running(); print(f"[running after {time.time()-t:.1f}s]")
t=time.time(); r=sb.exec(sys.argv[1], working_directory=(sys.argv[2] if len(sys.argv)>2 else None))
print(f"[exit={r.exit_code} {time.time()-t:.1f}s]"); print(r.stdout[-6000:] if r.stdout else ""); print("STDERR:", (r.stderr or "")[-3000:])

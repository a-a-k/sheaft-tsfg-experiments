"""Check whether fork/exec history changes wait4/getrusage peak-RSS interpretation."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    root=Path('artifacts/memory-counter');root.mkdir(parents=True,exist_ok=True)
    child="""import json,resource
from pathlib import Path
status={line.split(':')[0]:line.split(':',1)[1].strip() for line in Path('/proc/self/status').read_text().splitlines()}
print(json.dumps(dict(self_ru_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                     VmHWM_kib=int(status['VmHWM'].split()[0]),VmRSS_kib=int(status['VmRSS'].split()[0]))))
"""
    # This deliberately resident parent is an instrumentation probe, not a simulator.
    allocation=bytearray(256*2**20)
    rows=[]
    for label,command in [('direct',[sys.executable,'-c',child]),
        ('fresh-intermediate',[sys.executable,'-c',
          'import subprocess,sys; subprocess.run([sys.executable,"-c",'+repr(child)+'],check=True)'])]:
        output=root/(label+'.json')
        with output.open('w') as target:
            process=subprocess.Popen(command,stdout=target,start_new_session=True)
            _,status,usage=os.wait4(process.pid,0)
            process.returncode=os.waitstatus_to_exitcode(status)
        assert process.returncode==0
        rows.append(dict(label=label,parent_allocation_bytes=len(allocation),wait4_maxrss_kib=usage.ru_maxrss,
                         **json.loads(output.read_text())))
    direct,clean=rows
    inherited=direct['self_ru_maxrss_kib']>4*direct['VmHWM_kib']
    summary=dict(status='PASS',inherited_peak_observed=inherited,measurements=rows,
        interpretation='Frozen rusage peak includes process-launch history; it is not isolated simulator image VmHWM',
        source='https://man7.org/linux/man-pages/man2/getrusage.2.html')
    assert inherited,'Expected mechanism did not reproduce; reassess interpretation'
    assert clean['self_ru_maxrss_kib']<direct['self_ru_maxrss_kib']/4
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))


if __name__=='__main__':main()

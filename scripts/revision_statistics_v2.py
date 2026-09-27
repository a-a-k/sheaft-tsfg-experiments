"""Censored PBR intervals and completion-aware supplementary reserve summaries."""
import math
import statistics


def speedup_bounds(processes):
    """Bounds on a hypothetical completed-time ratio, never a substitute for S."""
    groups={engine:[p for p in processes if p['engine']==engine] for engine in ('des','tsfg')}
    assert all(len(rows)==2 for rows in groups.values())
    def interval(row):
        if row['performance_status']=='MEASURED':
            value=row['T_total_s'];assert value>0
            return value,value
        if row['performance_status']=='TIMEOUT':
            value=row['T_total_lower_bound_s'];assert value>0
            return value,math.inf
        return None
    times={engine:[interval(p) for p in rows] for engine,rows in groups.items()}
    if any(value is None for rows in times.values() for value in rows):
        return dict(lower=None,upper=None,status='UNAVAILABLE')
    low_des=math.prod(x[0] for x in times['des']);high_des=math.prod(x[1] for x in times['des'])
    low_tsfg=math.prod(x[0] for x in times['tsfg']);high_tsfg=math.prod(x[1] for x in times['tsfg'])
    lower=math.sqrt(low_des/high_tsfg) if math.isfinite(high_tsfg) else 0.
    upper=math.sqrt(high_des/low_tsfg) if math.isfinite(high_des) else None
    censored=any(p['performance_status']=='TIMEOUT' for p in processes)
    return dict(lower=lower,upper=upper,status='CENSORED_BOUND' if censored else 'COMPLETE_TIMES',
        accuracy_scope='Conditional on any unfinished processes eventually returning correct full results')


def tardiness(rows,deadline):
    """Full-job-set makespan lateness; do not impute a horizon for unknown Cmax."""
    known=[max(0,row['cmax']-deadline)/1100 for row in rows if row['completion_known']]
    unknown=[row for row in rows if not row['completion_known']]
    assert all(row['cmax'] is None for row in unknown)
    bounds=[max(0,row['completion_lower_bound']-deadline)/1100 for row in unknown
            if row.get('completion_lower_bound') is not None]
    result=dict(n=len(rows),known=len(known),unknown=len(unknown),
        deadlocked=sum(row['run_status']=='DEADLOCK' for row in unknown),
        unit='seconds',mean=None,p50=None,p95=None,
        unknown_tardiness_lower_bounds_s=bounds)
    if not unknown:
        assert known
        # Same linear interpolation convention as the primary NumPy summaries.
        values=sorted(known)
        def quantile(p):
            position=(len(values)-1)*p;index=int(position);fraction=position-index
            return values[index]+fraction*(values[min(index+1,len(values)-1)]-values[index])
        result.update(mean=statistics.mean(values),p50=quantile(.5),p95=quantile(.95))
    return result

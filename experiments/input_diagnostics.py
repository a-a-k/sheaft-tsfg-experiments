"""Descriptive diagnostics of an already validated fixed baseline schedule."""
import statistics


def describe(data):
    ops=data['operations'];machines=len(data['queues'])
    horizon=max(o['planned_end'] for o in ops)
    work=[0]*machines;earliest=[0]*len(ops)
    for o in ops:
        assert all(p<o['id'] for p in o['predecessors'])
        work[o['machine']]+=o['work']
        earliest[o['id']]=max([o['release'],*[earliest[p] for p in o['predecessors']]])+o['work']
    intervals=sorted((o['planned_start'],o['planned_end']) for o in ops)
    cursor=0;idle=0;largest=0;gaps=0
    for start,end in intervals:
        if start>cursor:
            length=start-cursor;idle+=length;largest=max(largest,length);gaps+=1
        cursor=max(cursor,end)
    events=sorted({t for interval in intervals for t in interval})
    spacing=[b-a for a,b in zip(events,events[1:])]
    quartiles=statistics.quantiles(spacing,n=4,method='inclusive') if len(spacing)>1 else spacing*3
    lower=max(max(work),max(earliest))
    assert lower<=horizon and max(work)<=horizon
    return dict(operations=len(ops),jobs=len(data['jobs']),machines=machines,C0_ticks=horizon,
        lower_bound_ticks=lower,critical_technology_path_with_releases_ticks=max(earliest),
        machine_work_lower_bound_ticks=max(work),machine_utilization=[v/horizon for v in work],
        total_processing_ticks=sum(work),global_idle_ticks=idle,global_idle_fraction=idle/horizon,
        longest_global_idle_ticks=largest,global_idle_intervals=gaps,distinct_event_boundaries=len(events),
        inter_event_ticks=dict(min=min(spacing),median=statistics.median(spacing),max=max(spacing),quartiles=quartiles),
        scope='Validated nominal schedule on [0,C0]; processing only, zero setup and transport')

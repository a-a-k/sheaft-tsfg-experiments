"""Independent exact event solver of the public homogeneous fluid contract."""
from fractions import Fraction as F


def solve(case,horizon):
    stop=F(str(horizon));q=[F(v) for v in case['volumes']]+[F(0)]
    rates=[F(v) for v in case['rates']];sink=F(case['sink_rate'])
    capacity=None if case['capacity'] is None else F(case['capacity'])
    downs=[(F(a),F(b)) for a,b in case['sink_down']]
    peaks=q[:];produced=F(0);integral=F(0);t=F(0);events=0;completion=None
    volume=sum(q)
    while t<stop and produced<volume:
        u=[rate if qi>0 else F(0) for rate,qi in zip(rates,q)]
        v=F(0) if any(a<=t<b for a,b in downs) else sink
        incoming=sum(u)
        if q[-1]==0:v=min(v,incoming)
        if capacity is not None and q[-1]==capacity and incoming>v:
            u=[value*v/incoming for value in u];incoming=v
        derivative=incoming-v
        choices=[stop-t]
        choices += [point-t for interval in downs for point in interval if point>t]
        choices += [qi/ui for qi,ui in zip(q,u) if qi>0 and ui>0]
        if derivative<0:choices.append(q[-1]/(-derivative))
        elif derivative>0 and capacity is not None:choices.append((capacity-q[-1])/derivative)
        dt=min(value for value in choices if value>0)
        before=sum(q)
        for i,ui in enumerate(u):q[i]-=ui*dt
        q[-1]+=derivative*dt;produced+=v*dt;t+=dt;events+=1
        assert all(value>=0 for value in q)
        assert capacity is None or q[-1]<=capacity
        assert sum(q)+produced==volume
        integral+=(before+sum(q))*dt/2
        peaks=[max(a,b) for a,b in zip(peaks,q)]
        if produced==volume:completion=t
        assert events<10000
    return dict(produced=float(produced),queue_at_D=[float(v) for v in q],queue_max=[float(v) for v in peaks],
        wip_integral=float(integral),cmax=float(completion) if completion is not None else None,
        completion_known=completion is not None,mission_success=completion is not None,
        completion_lower_bound=None if completion is not None else float(stop),
        material_balance_max_abs=0,events=events)

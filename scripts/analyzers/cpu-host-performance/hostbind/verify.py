"""Business outcome comparison; affinity readback alone is never performance proof."""
import math
import statistics


def percentile(values, q):
    ordered=sorted(values);pos=(len(ordered)-1)*q;lo=int(pos);hi=min(lo+1,len(ordered)-1)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(pos-lo)


def compare_measurements(before, after, min_runs=3, min_samples=30,
                         min_gain=2.0, max_tail_regression=5.0):
    def result(status, reason, **extra):
        return dict(schema_version=1,status=status,decision='KEEP' if status=='PASS' else
                    ('ROLLBACK' if status in ('REGRESSION','NO_GAIN') else 'INCONCLUSIVE'),reason=reason,**extra)
    try:
        for obj in (before,after):
            if obj.get('schema_version')!=1:raise ValueError('measurement schema_version must be 1')
            workload=obj['workload']
            required=('model','batch_size','parallelism','dataset','framework','precision','sequence_length')
            if not isinstance(workload,dict) or any(k not in workload or workload[k] is None for k in required):
                raise ValueError('workload fingerprint missing required fields')
            if not isinstance(obj.get('errors'),int) or obj['errors']<0:raise ValueError('errors must be a nonnegative integer')
        if before['workload']!=after['workload']:raise ValueError('different workload fingerprints')
        if before['metric']!=after['metric']:raise ValueError('different metric name/unit/direction')
        if (before['warmup']!=after['warmup'] or len(before['runs'])!=len(after['runs']) or
            [len(r) for r in before['runs']]!=[len(r) for r in after['runs']]):
            raise ValueError('different sampling protocol / warmup / run sample counts')
        metric=before['metric']
        if metric['direction'] not in ('higher','lower') or not metric.get('unit') or not metric.get('name'):
            raise ValueError('invalid metric')
        if before['errors']:raise ValueError('baseline contains business errors')
        if after['errors']:return result('REGRESSION','Business errors after binding')
        samples=[];run_medians=[]
        for obj in (before,after):
            warmup=obj['warmup'];runs=obj['runs']
            if type(warmup) is not int or warmup<0 or not isinstance(runs,list) or len(runs)<min_runs:
                raise ValueError('insufficient independent runs / invalid warmup')
            clean=[]
            for run in runs:
                if not isinstance(run,list):raise ValueError('run must be an array')
                if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in run):
                    raise ValueError('samples must be finite positive numbers')
                values=run[warmup:]
                if len(values)<min_samples:raise ValueError('insufficient post-warmup samples per run')
                clean.append(values)
            samples.append([v for run in clean for v in run])
            run_medians.append([statistics.median(run) for run in clean])
        b,a=[statistics.median(v) for v in run_medians]
        sign=1 if metric['direction']=='higher' else -1
        gain=sign*(a/b-1)*100
        # For throughput, the bad tail is P5; for latency it is P95.
        q=.05 if sign==1 else .95
        bt,at=[percentile(v,q) for v in samples]
        tail_regression=-sign*(at/bt-1)*100
        spread=max((max(v)-min(v))/statistics.median(v)*100 for v in run_medians)
        extra=dict(metric=metric,before_median=b,after_median=a,gain_percent=gain,
                   before_tail=bt,after_tail=at,tail_percentile=q*100,
                   tail_regression_percent=tail_regression,run_medians=run_medians,
                   run_spread_percent=spread,thresholds=dict(min_gain_percent=min_gain,
                   max_tail_regression_percent=max_tail_regression,min_runs=min_runs,min_samples=min_samples))
        tolerance=1e-9  # Avoid classifying an exact percentage threshold by float representation.
        if gain < -min_gain-tolerance or tail_regression>max_tail_regression+tolerance:
            return result('REGRESSION','Business median or bad tail regressed',**extra)
        if spread>max(5.0,abs(gain)):
            return result('INCONCLUSIVE','Between-run variance exceeds observed gain; repeat A/B/A',**extra)
        if gain<min_gain-tolerance:return result('NO_GAIN','Gain below configured experiment threshold',**extra)
        return result('PASS','Business gain passes median/tail checks; empirical A/B evidence',**extra)
    except (KeyError,TypeError,ValueError,ZeroDivisionError,OverflowError) as exc:
        return result('INCONCLUSIVE',str(exc))

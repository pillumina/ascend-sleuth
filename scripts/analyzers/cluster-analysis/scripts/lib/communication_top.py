"""Bounded elapsed-time rankings shared by the cluster and advisor reports."""
from bisect import insort
import re

from lib.common import to_f
from lib.config import AGG_ROWS


_TOTALS = {name.lower() for name in AGG_ROWS} | {'all'}
_TYPE_PREFIX = re.compile(r'^(?:hcom|hccl|nccl)', re.IGNORECASE)
_ALIASES = {
    'batchsendrecv': 'BatchSendRecv', 'batchsendreceive': 'BatchSendRecv',
    'allgatherv': 'AllGatherV', 'allgather': 'AllGather', 'allreduce': 'AllReduce',
    'alltoallvc': 'AllToAllVC', 'alltoallv': 'AllToAllV', 'alltoall': 'AllToAll',
    'reducescatterv': 'ReduceScatterV', 'reducescatter': 'ReduceScatter',
    'broadcast': 'Broadcast', 'reduce': 'Reduce', 'scatter': 'Scatter', 'gather': 'Gather',
    'sendrecv': 'SendRecv', 'sendreceive': 'SendRecv', 'send': 'Send',
    'receive': 'Receive', 'recv': 'Receive', 'barrier': 'Barrier',
}
_TYPE = re.compile('|'.join(sorted(_ALIASES, key=len, reverse=True)))


def communication_type(name):
    op = name.partition('@')[0].strip().lower()
    if not op or op in _TOTALS or re.fullmatch(r'plan\d+', op):
        return None
    compact = re.sub(r'[^a-z0-9]', '', _TYPE_PREFIX.sub('', op))
    match = _TYPE.match(compact)
    return _ALIASES[match[0]] if match else '其他通信'


def communication_tops(rows, name_key, elapsed_key, overall_limit=0):
    """Select ten per type and optionally preserve the legacy overall ranking."""
    groups, overall = {}, []

    def keep(board, item, limit):
        if len(board) < limit or item < board[-1]:
            insort(board, item)
            if len(board) > limit:
                board.pop()

    for position, row in enumerate(rows):
        name = str(row.get(name_key) or '')
        kind = communication_type(name)
        elapsed = to_f(row.get(elapsed_key), None)
        if kind is None or elapsed is None:
            continue
        item = (-elapsed, name, position, row)
        keep(groups.setdefault(kind, []), item, 10)
        if overall_limit:
            keep(overall, item, overall_limit)
    return ({kind: [entry[-1] for entry in board] for kind, board in sorted(groups.items())},
            [entry[-1] for entry in overall])

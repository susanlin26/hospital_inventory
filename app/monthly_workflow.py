"""異常原因、五種進度及可回溯統計。純函式不改寫原始財務資料。"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Taipei')
STATES = ('待填原因', '待審核', '改善中', '待確認結案', '已完成')
CAUSE_OPTIONS = {
    'usage': ['住院人日數變動', '照護需求改變', '集中領用', '供應商調價', '其他'],
    'purchase': ['供應商調價', '供應商變更', '優惠結束', '其他'],
    'high': ['安全備貨', '最低訂購量', '需求下降', '停用', '其他'],
    'low': ['需求增加', '交貨延誤', '請購不及', '安全存量不足', '其他'],
    'idle': ['安全備貨', '最低訂購量', '需求下降', '停用', '其他'],
}
LEGACY_CAUSES = ['住院人日變化', '照護需求改變', '耗用單位成本變化', '盤點或異動調整', '備貨安排', '其他']


def status(x):
    s = x.get('workflow_status') or x.get('status')
    if s == '待補充':  # 舊案及舊歷程相容；不再產生獨立待補充狀態。
        return '改善中' if x.get('return_stage') == 'result' else '待填原因'
    if x.get('workflow_status') in STATES:
        return x['workflow_status']
    if s in STATES and s != '改善中':
        return s
    if s == '待會計審核':
        return '待確認結案' if x.get('submission') == 'improvement' else '待審核'
    if s in ('合理原因已核准', '已驗證改善'):
        return '改善中' if x.get('follow_up') and not x.get('follow_up_completed') else '已完成'
    return '待填原因'


def normalize(x):
    result = deepcopy(x)
    result['workflow_status'] = status(x)
    if x.get('status') in ('合理原因已核准', '已驗證改善'):
        result.setdefault('cause_approved', True)
        result.setdefault('approved_cause', dict(category=x.get('cause_category'), note=x.get('note'), evidence=x.get('evidence'), at=x.get('review_date')))
    if result['workflow_status'] == '已完成':
        result.setdefault('completed_at', x.get('review_date'))
    return result


def improvement(x):
    """送出需要改善即納入，不以會計已核准作為入口條件。"""
    return bool(x.get('follow_up') and (x.get('submitted_at') or x.get('cause_approved')))


def next_owner(x):
    s = status(x)
    if s in ('待審核', '待確認結案'):
        return '會計／覆核主管'
    if s == '改善中':
        return '前線人員'
    return '—' if s == '已完成' else '前線人員'


def overdue(x, today=None):
    today = today or datetime.now(TZ).date()
    if not x.get('follow_up') or status(x) == '已完成' or not x.get('deadline'):
        return 0
    try:
        return max(0, (today - date.fromisoformat(x['deadline'])).days)
    except ValueError:
        return 0


def record(x, action, user, now=None):
    now = now or datetime.now(TZ).isoformat()
    point = {k: deepcopy(v) for k, v in x.items() if k not in ('history', 'latest_data', 'comparisons', 'link_candidates')}
    x.setdefault('history', []).append(dict(at=now, action=action, actor=user.get('name', '系統'), user_id=user.get('id'), snapshot=point))


def as_of(x, cutoff):
    """不拿今天的狀態回填歷史季末；缺少歷史證據時回傳未知。"""
    candidates = [e for e in x.get('history', []) if e['at'][:10] <= cutoff]
    if candidates:
        return normalize(candidates[-1]['snapshot'])
    # v0.9.8 的待處理／審核／完成時間仍可使用，但不推定缺失的中間狀態。
    review = x.get('review_date')
    if not x.get('history') and review and review[:10] <= cutoff:
        return normalize(x)
    return None


def stats(rows, start, end):
    index = {(t['id'], k): (t, x) for t in rows for k, x in t['body'].get('items', {}).items()}
    visible = []
    for (cid, k), (t, x) in index.items():
        if x.get('tracking_excluded_at') and x['tracking_excluded_at'][:10]<=end and status(x)!='已完成':
            continue
        if t['period'] > end[:7]:
            continue
        at = as_of(x, end)
        visible.append((t, k, at, x))
    owners = {}
    causes, progress, hospital, review = {}, {s: 0 for s in STATES}, {}, dict(pending=0, oldest_days=0, reviewed=0, returned=0, return_reasons=[])
    new_count = unconfirmed = unknown = open_count = late = due = completed = completed_count = ontime = 0
    repeated = recurrence = 0
    amounts = {'usage_increase': D(0), 'usage_decrease': D(0), 'purchase_increase': D(0), 'purchase_decrease': D(0), 'inventory': D(0)}
    inventory = {}
    effects, details, identities = [], [], {}
    for t, k, x, raw in visible:
        new = start[:7] <= t['period'] <= end[:7]
        identity = (t['hospital'], t['kind'], k, raw['data'].get('name'))
        identities.setdefault(identity, []).append((t['period'], t, raw))
        if new:
            new_count += 1
            cause = (x or {}).get('approved_cause') if x else None
            if x and x.get('linked_to'):
                link = x['linked_to']; target = index.get((link['case_id'], link['key']))
                root = as_of(target[1], end) if target else None
                cause = (root or {}).get('approved_cause')
            if cause and cause.get('category'):
                label = cause['category']; group = causes.setdefault((t['kind'], label), dict(kind=t['kind'], cause=label, count=0, follow_up=0, overdue=0, quarters={str(q):0 for q in range(1,5)}))
                group['count'] += 1
                group['quarters'][str((int(t['period'][5:])-1)//3+1)] += 1
                group['follow_up'] += bool((root if x and x.get('linked_to') else x) and (root if x and x.get('linked_to') else x).get('follow_up'))
                group['overdue'] += bool(x and overdue(x, date.fromisoformat(end)))
            else:
                unconfirmed += 1
            d = raw['data']; value = d.get('difference') if t['kind'] == 'usage' else d.get('purchase_impact') if t['kind'] == 'purchase' else None
            if value is not None:
                value = D(str(value)); amounts[('usage' if t['kind'] == 'usage' else 'purchase') + ('_increase' if value >= 0 else '_decrease')] += abs(value)
            if t['kind'] in ('high', 'low', 'idle'):
                inventory[(t['hospital'], t['period'], k)] = max(inventory.get((t['hospital'], t['period'], k), D(0)), D(str(d.get('ending') or 0)))
        if not x:
            unknown += 1
            continue
        effective = x
        if x.get('linked_to'):
            link=x['linked_to']; target=index.get((link['case_id'],link['key']))
            effective=(as_of(target[1],end) if target else None) or x
        s = status(effective)
        details.append(dict(case_id=t['id'], key=k, hospital=t['hospital'], period=t['period'], kind=t['kind'], code=raw['data']['code'], name=raw['data']['name'], status=s, cause=(effective.get('approved_cause') or {}).get('category'), owner=effective.get('owner'), deadline=effective.get('deadline'), overdue=overdue(effective, date.fromisoformat(end)), linked=bool(x.get('linked_to'))))
        if not x.get('linked_to'):
            progress[s] += 1
            if s != '已完成':
                open_count += 1
            elif start <= (x.get('completed_at') or '')[:10] <= end:
                completed_count += 1
            if overdue(x, date.fromisoformat(end)):
                late += 1
            if x.get('follow_up'):
                owner_key=(t['hospital'],x.get('owner') or '舊案未記錄')
                owner=owners.setdefault(owner_key,dict(hospital=t['hospital'],owner=owner_key[1],open=0,overdue=0))
                owner['open'] += s != '已完成'; owner['overdue'] += bool(overdue(x,date.fromisoformat(end)))
                h = hospital.setdefault(t['hospital'], dict(hospital=t['hospital'], open=0, overdue=0, due=0, completed=0, ontime=0))
                h['open'] += s != '已完成'; h['overdue'] += bool(overdue(x, date.fromisoformat(end)))
                if x.get('deadline') and start <= x['deadline'] <= end:
                    due += 1; h['due'] += 1
                    done = s == '已完成' and bool(x.get('completed_at')) and x['completed_at'][:10] <= end
                    timely = done and x['completed_at'][:10] <= x['deadline']
                    completed += done; ontime += timely; h['completed'] += done; h['ontime'] += timely
                if s == '已完成' and start <= (x.get('completed_at') or '')[:10] <= end:
                    effects.append(dict(case_id=t['id'], key=k, hospital=t['hospital'], code=raw['data']['code'], kind=t['kind'], before=x['data'], after=x.get('verified_data'), result=x.get('result_note'), evidence=x.get('result_evidence'), completed_at=x.get('completed_at')))
            if s in ('待審核', '待確認結案'):
                review['pending'] += 1
                stamp = x.get('result_at') if s == '待確認結案' else x.get('submitted_at')
                if stamp:
                    review['oldest_days'] = max(review['oldest_days'], (date.fromisoformat(end) - date.fromisoformat(stamp[:10])).days)
        for e in raw.get('history', []):
            if start <= e['at'][:10] <= end:
                review['reviewed'] += e['action'] in ('approve', 'approve_follow', 'finish', 'reject')
                review['returned'] += e['action'] == 'reject'
                if e['action'] == 'reject':
                    review['return_reasons'].append(dict(case_id=t['id'],key=k,hospital=t['hospital'],code=raw['data']['code'],at=e['at'],reason=e['snapshot'].get('review_note'),reviewer=e.get('actor')))
    consecutive = []
    for identity, entries in identities.items():
        entries.sort(key=lambda e: e[0]); periods = sorted({e[0] for e in entries}); maximum = run = 1
        from .engine import previous
        for a, b in zip(periods, periods[1:]):
            run = run + 1 if previous(b) == a else 1; maximum = max(maximum, run)
        if maximum > 1 and any(start[:7] <= p <= end[:7] for p in periods):
            repeated += 1
            consecutive.append(dict(hospital=identity[0], kind=identity[1], code=entries[-1][2]['data']['code'], months=maximum, periods=periods))
        for i, (p, t, raw) in enumerate(entries):
            if start[:7] <= p <= end[:7] and any((e.get('snapshot', {}).get('completed_at') or '')[:7] < p and status(e.get('snapshot', {})) == '已完成' for _, _, prior in entries[:i] for e in prior.get('history', []) if e['at'][:10] <= end):
                recurrence += 1
    # 庫存金額為本期新增異常涉及金額，跨類型同院月品項只計一次。
    amounts['inventory'] = sum(inventory.values(), D(0))
    return dict(start=start, end=end, new_count=new_count, unconfirmed=unconfirmed, unknown_history=unknown, open_count=open_count, completed_count=completed_count, overdue=late, due=due, completed=completed, ontime=ontime, completion_rate=D(completed) / due * 100 if due else None, ontime_rate=D(ontime) / due * 100 if due else None, repeated=repeated, recurrence=recurrence, causes=sorted(causes.values(), key=lambda x: -x['count']), progress=progress, hospitals=list(hospital.values()), owners=list(owners.values()), review={**review, 'return_rate': D(review['returned']) / review['reviewed'] * 100 if review['reviewed'] else None}, amounts=amounts, effects=effects, consecutive=consecutive, details=details)

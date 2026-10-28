"""Preserve saved review revisions without changing the existing export fields."""
from datetime import datetime, timezone, timedelta

REVIEW_FIELDS = ('review_label', 'notes', 'reviewer')
VALID_LABELS = {'unreviewed', 'similar', 'different', 'manhole', 'uncertain'}


def updated_review(candidate, data, now=None):
    label = data.get('review_label', 'unreviewed')
    if label not in VALID_LABELS:
        raise ValueError('Invalid review decision.')
    values = dict(review_label=label, notes=str(data.get('notes', ''))[:5000],
                  reviewer=str(data.get('reviewer', candidate.get('reviewer', '')))[:100])
    previous = {key: candidate.get(key, 'unreviewed' if key == 'review_label' else '')
                for key in REVIEW_FIELDS}
    if previous == values:
        return dict(candidate)
    timestamp = now or datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    history = list(candidate.get('review_history', []))
    if not history:
        history.append(dict(previous, reviewed_at=candidate.get('reviewed_at'),
                            revision=0, origin='baseline'))
    history.append(dict(values, reviewed_at=timestamp, revision=len(history), origin='saved'))
    return dict(candidate, **values, reviewed_at=timestamp, review_history=history)


def cleared_reviews(candidates, now=None):
    """Reset current decisions and notes while retaining each previous saved state."""
    timestamp = now or datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    rows, count = [], 0
    for candidate in candidates:
        updated = updated_review(candidate, dict(review_label='unreviewed', notes='', reviewer=''), timestamp)
        if updated != candidate:
            updated['review_history'][-1] = dict(updated['review_history'][-1], origin='cleared_all')
            count += 1
        rows.append(updated)
    return rows, count

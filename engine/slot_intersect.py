"""Intersect free-slot lists from multiple calendar sources.

Each slot list is a list of dicts: {"start": "HH:MM", "end": "HH:MM", "duration_min": int}.
The intersection returns only time ranges that appear as free in ALL sources.
"""


def _parse_minutes(hhmm):
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _format_hhmm(minutes):
    """Convert minutes since midnight to 'HH:MM'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def intersect_free_slots(slot_lists):
    """Return the intersection of multiple free-slot lists.

    Only time ranges free in ALL sources are returned.
    Minimum resulting slot duration is 15 minutes.
    """
    if not slot_lists:
        return []
    if len(slot_lists) == 1:
        return slot_lists[0]

    # Convert each list to sorted (start_min, end_min) intervals
    interval_sets = []
    for slots in slot_lists:
        intervals = []
        for s in slots:
            intervals.append((_parse_minutes(s["start"]), _parse_minutes(s["end"])))
        intervals.sort()
        interval_sets.append(intervals)

    # Pairwise intersect
    result = interval_sets[0]
    for other in interval_sets[1:]:
        result = _intersect_two(result, other)

    # Convert back to slot dicts, filter short slots
    output = []
    for start, end in result:
        dur = end - start
        if dur >= 15:
            output.append({
                "start": _format_hhmm(start),
                "end": _format_hhmm(end),
                "duration_min": dur,
            })
    return output


def _intersect_two(a, b):
    """Intersect two sorted interval lists."""
    result = []
    i, j = 0, 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        # Advance the interval that ends first
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result

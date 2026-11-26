"""Plan a bounded age-band revision from proposed released profile values."""

from collections import Counter, defaultdict

from raksha.detection import identifier_kind, is_coarse_location


def age_value(value):
    if type(value) not in (str, int):
        return None
    text = str(value).strip()
    if 1 <= len(text) <= 3 and text.isdecimal() and int(text) <= 125:
        return int(text)
    return None


def proposed_profile_fields(record, width, geography_token):
    """Return only generalised ages and keys for equality on coarse locations."""
    if not isinstance(record, dict):
        return (), ()
    ages, places = set(), set()
    pending = [record]
    while pending:
        fields = pending.pop()
        for label, value in fields.items():
            if isinstance(value, dict):
                pending.append(value)
            elif identifier_kind(label) == "AGE" and (age := age_value(value)) is not None:
                ages.add(age // width * width)
            elif is_coarse_location(label) and isinstance(value, str) and value.strip():
                places.add(geography_token(" ".join(value.casefold().split())))
    return tuple(sorted(ages)), tuple(sorted(places))


def plan_age_bands(candidates, width, min_group_size):
    """Widen only when a group of small profiles gains comparison peers."""
    ages, places = defaultdict(set), defaultdict(set)
    for patient, bands, geography in candidates:
        ages[patient].update(bands)
        places[patient].update(geography)

    signatures = {
        patient: (tuple(sorted(bands)), tuple(sorted(places[patient])))
        for patient, bands in ages.items()
        if bands
    }
    counts = Counter(signatures.values())
    offered = defaultdict(list)
    for patient, (bands, geography) in signatures.items():
        if counts[(bands, geography)] < min_group_size:
            wider = tuple(sorted({band // (2 * width) * (2 * width) for band in bands}))
            offered[wider, geography].append(patient)

    return frozenset(
        patient
        for cohort in offered.values()
        for patient in cohort
        if len(cohort) > counts[signatures[patient]]
    )

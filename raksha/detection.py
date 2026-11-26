"""Classify direct identifiers using their field labels."""

import re
import unicodedata

_FIELDS = {
    "NAME": (
        "name", "patient name", "patients name", "full name", "first name", "last name",
        "given name", "family name", "naam", "नाम", "relative name", "guardian",
        "guardian name", "attendant name", "pita pati ka naam", "मरीज का नाम",
        "मरीज़ का नाम", "रोगी का नाम", "अभिभावक का नाम",
    ),
    "MRN": (
        "uhid", "mrn", "patient id", "patient ref", "reg no", "registration no",
        "registration number", "ipd no", "opd no", "admission id", "hospital id", "hospital uhid",
    ),
    "PHONE": ("mobile", "mobile no", "mobile number", "phone", "phone no", "telephone"),
    "EMAIL": ("email", "email address"),
    "AADHAAR": ("aadhaar", "aadhaar no", "aadhaar number", "aadhar", "aadhar no"),
    "ABHA": ("abha", "abha no", "abha number", "abha address"),
    "PAN": ("pan", "pan no", "pan number"),
    "INSURANCE_ID": ("insurance id", "policy number", "member id"),
    "ADDRESS": ("address", "street", "house", "house no", "landmark", "locality", "pata"),
    "SOURCE_PATH": ("source path", "original filename", "source filename"),
    "ENCOUNTER": ("encounter id", "encounter ref"),
    "AGE": ("age", "age years", "umar", "उम्र"),
    "PIN": ("pin", "pin code", "zipcode", "zip", "postal code", "पिन"),
    "VILLAGE": ("village", "village mohalla", "gaon", "gram", "गाँव", "गांव", "ग्राम"),
    "DOB": ("dob", "dob mm dd yyyy", "dob dd mm yyyy", "date of birth", "birth date",
            "janm tithi", "जन्म तिथि"),
}


def _normalize(label: str) -> str:
    label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", label)
    label = re.sub(r"[_/().:-]+", " ", label.replace("'", "").replace("’", ""))
    return " ".join(label.casefold().split())


_KINDS = {_normalize(label): kind for kind, labels in _FIELDS.items() for label in labels}


def identifier_kind(label: str) -> str | None:
    return _KINDS.get(_normalize(label))


_COARSE_LOCATIONS = {
    "tehsil": 1, "tahsil": 1, "तहसील": 1,
    "district": 2, "jila": 2, "जिला": 2,
    "state": 3, "country": 4,
}


def is_coarse_location(label: str) -> bool:
    return _normalize(label) in _COARSE_LOCATIONS


def village_region(fields) -> str | None:
    """Use the nearest explicit region only when that level is unambiguous."""
    choices = {1: set(), 2: set()}
    for label, value in fields:
        rank = _COARSE_LOCATIONS.get(_normalize(label))
        if rank in choices and isinstance(value, str):
            region = " ".join(value.split())
            if region and len(region) <= 80 and all(
                char.isalpha() or re.fullmatch(r"[\u0900-\u097f .'-]", char) for char in region
            ):
                choices[rank].add(region)
    return next((next(iter(values)) for values in choices.values() if len(values) == 1), None)


_HINDI_NAME = r"[\u0904-\u0939][\u0900-\u097f]*"
_LATIN_NAME = r"[A-Z][a-z]+(?:[.'’-][A-Za-z]+)*"
_NAME_WORD = rf"(?:{_LATIN_NAME}|{_HINDI_NAME})"
_EXPLICIT_NAME = re.compile(
    rf"(?m)^([ \t]*(?:(?i:patient|pt\.?|attendant|guardian|mareez ka naam|"
    rf"rogi ka naam)|मरी[ज़ज] का नाम|मरीज़ का नाम|रोगी का नाम|अभिभावक का नाम)"
    rf"[ \t]*:[ \t]*)({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}})"
)
_HONORIFIC_NAME = re.compile(
    rf"(?<![\w.\u0900-\u097f])({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
    r"(?=[ \t]+(?i:ji|sahab|saheb|didi|behenji|bhaiya)[ \t]+(?i:ka|ki|ke|ne|ko)\b)"
)
_CLINICIAN_PREFIX = re.compile(r"(?i)(?:\bdr\.?|\bdoctor|डॉ\.?)\s*$")
_CLINICAL_WORDS = frozenset({
    "bp", "pulse", "temp", "spo2", "k/c/o", "dose", "report",
    "parkinson", "addison", "dengue", "fever", "diabetes", "asthma",
})


def redact_contextual_names(text):
    count = 0

    def replace_explicit(match):
        nonlocal count
        if any(word.casefold() in _CLINICAL_WORDS for word in match[2].split()):
            return match[0]
        count += 1
        return match[1] + "[NAME]"

    def replace_honorific(match):
        nonlocal count
        if (_CLINICIAN_PREFIX.search(text[max(0, match.start() - 16):match.start()])
                or any(word.casefold() in _CLINICAL_WORDS for word in match[0].split())):
            return match[0]
        count += 1
        return "[NAME]"

    text = _EXPLICIT_NAME.sub(replace_explicit, text)
    text = _HONORIFIC_NAME.sub(replace_honorific, text)
    return text, count


_NAME_TOKEN = re.compile(
    r"(?:[^\W\d_]|[\u0900-\u097f])+(?:[.'’-](?:[^\W\d_]|[\u0900-\u097f])+)*"
)
_CLINICIAN_CONTEXT = re.compile(
    r"(?i)(?:\b(?:dr\.?|doctor|consultant|attending|treating physician|signed by)"
    r"|डॉ\.?)\s*[:=-]?\s*$"
)


def _name_key(parts):
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in parts)


def known_name_keys(record):
    """Collect complete names from explicit patient and relative fields only."""
    if not isinstance(record, dict):
        return set()
    fields = [record]
    for label in ("patient", "demographics"):
        if isinstance(record.get(label), dict):
            fields.append(record[label])
    names = set()
    for scope in fields:
        explicit_identity = scope is not record or any(identifier_kind(label) == "MRN" for label in scope)
        split = {}
        for label, value in scope.items():
            if not isinstance(value, str) or identifier_kind(label) != "NAME":
                continue
            field = _normalize(label)
            if field == "name" and not explicit_identity:
                continue
            if field in {"first name", "given name", "last name", "family name"}:
                split["first" if field in {"first name", "given name"} else "last"] = value
            parts = value.split()
            if 2 <= len(parts) <= 4 and all(_NAME_TOKEN.fullmatch(part) for part in parts):
                names.add(_name_key(parts))
        if len(split) == 2:
            parts = (split["first"] + " " + split["last"]).split()
            if 2 <= len(parts) <= 4 and all(_NAME_TOKEN.fullmatch(part) for part in parts):
                names.add(_name_key(parts))
    return names


def redact_known_names(text, names):
    """Replace exact, complete names while keeping clinician occurrences."""
    if not names:
        return text, 0
    tokens = list(_NAME_TOKEN.finditer(text))
    spans = []
    index = 0
    while index + 1 < len(tokens):
        start = tokens[index].start()
        prefix = text[max(0, start - 48):start].rsplit("\n", 1)[-1]
        match = None
        for size in range(min(4, len(tokens) - index), 1, -1):
            phrase = tokens[index:index + size]
            if any(not re.fullmatch(r"[ \t]+", text[a.end():b.start()])
                   for a, b in zip(phrase, phrase[1:])):
                continue
            if _name_key(token[0] for token in phrase) in names:
                match = size
                if not _CLINICIAN_CONTEXT.search(prefix):
                    spans.append((start, phrase[-1].end()))
                break
        index += match or 1
    if not spans:
        return text, 0
    chunks = []
    previous = 0
    for start, end in spans:
        chunks.extend((text[previous:start], "[NAME]"))
        previous = end
    chunks.append(text[previous:])
    return "".join(chunks), len(spans)

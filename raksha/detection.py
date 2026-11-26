"""Classify direct identifiers using their field labels."""

import re
import unicodedata

_FIELDS = {
    "NAME": (
        "name", "patient name", "patients name", "full name", "first name", "last name",
        "given name", "family name", "naam", "नाम", "relative name", "guardian",
        "guardian name", "attendant name", "pita pati ka naam", "मरीज का नाम",
        "मरीज़ का नाम", "रोगी का नाम", "अभिभावक का नाम",
        "पिता का नाम", "पति का नाम", "पिता पति का नाम", "परिजन का नाम",
    ),
    "MRN": (
        "uhid", "mrn", "patient id", "patient ref", "reg no", "registration no",
        "registration number", "ipd no", "opd no", "admission id", "hospital id", "hospital uhid",
    ),
    "PHONE": ("mobile", "mobile no", "mobile number", "phone", "phone no", "telephone",
              "मोबाइल", "मोबाइल नंबर", "फ़ोन", "फोन", "दूरभाष"),
    "EMAIL": ("email", "email address"),
    "AADHAAR": ("aadhaar", "aadhaar no", "aadhaar number", "aadhar", "aadhar no"),
    "ABHA": ("abha", "abha no", "abha number", "abha address"),
    "PAN": ("pan", "pan no", "pan number"),
    "INSURANCE_ID": ("insurance id", "insurance no", "insurance number", "policy no",
                     "policy number", "member id", "pmjay id", "insurance member id"),
    "ADDRESS": ("address", "address note", "postal address", "street", "house", "house no", "landmark", "locality", "pata",
                "पता", "मकान", "मकान नंबर", "मोहल्ला"),
    "SOURCE_PATH": ("source path", "original filename", "source filename"),
    "ENCOUNTER": ("encounter id", "encounter ref"),
    "AGE": ("age", "age years", "umar", "उम्र"),
    "PIN": ("pin", "pin code", "zipcode", "zip", "postal code", "पिन"),
    "VILLAGE": ("village", "village mohalla", "city", "gaon", "gram", "गाँव", "गांव", "ग्राम"),
    "DOB": ("dob", "dob mm dd yyyy", "dob dd mm yyyy", "date of birth", "birth date",
            "janm tithi", "जन्म तिथि"),
}


def _normalize(label: str) -> str:
    label = unicodedata.normalize("NFKC", label)
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


def is_lower_region(label: str) -> bool:
    return _COARSE_LOCATIONS.get(_normalize(label)) in {1, 2} or identifier_kind(label) == "VILLAGE"


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
_LABELLED_NAME_WORD = rf"(?!(?:उम्र|आयु)(?![\u0900-\u097f])){_NAME_WORD}"
_EXPLICIT_NAME = re.compile(
    rf"(?m)^([ \t]*(?:(?i:patient|pt\.?|attendant|guardian|mareez ka naam|"
    rf"rogi ka naam)|मरी[ज़ज] का नाम|मरीज़ का नाम|रोगी का नाम|"
    rf"नाम|(?:अभिभावक|पिता(?:/पति)?|पति|परिजन) का नाम)"
    rf"[ \t]*:[ \t]*)({_LABELLED_NAME_WORD}(?:[ \t]+{_LABELLED_NAME_WORD}){{0,3}})"
)
_HONORIFIC_NAME = re.compile(
    rf"(?<![\w.\u0900-\u097f])({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
    r"(?=[ \t]+(?i:ji|sahab|saheb|saab|didi|behenji|bhaiya|bhai|babu)"
    r"[ \t]+(?i:ka|ki|ke|ne|ko)\b)"
)
_CLINICAL_POSSESSOR = re.compile(
    rf"(?<![\w.\u0900-\u097f])({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
    r"(?:[ \t]+[a-z]{2,12})?"
    r"(?=[ \t]+(?i:ka|ki|ke)[ \t]+(?i:BP|pulse|spo2|temp(?:erature)?|"
    r"sugar|glucose|report|tabiyat|ilaaj)\b)"
)
_HINDI_LOCATION = re.compile(
    r"(?m)(?<![\w\u0900-\u097f])(पता|ग्राम|गाँव|गांव|मोहल्ला|मकान(?: नंबर)?)"
    r"([ \t]*[:=][ \t]*)([^\r\n,;|]+)"
)
_LAB_REPORT_NAME = re.compile(
    rf"(?m)^([ \t]*(?i:(?:lab[ \t]+)?report[ \t]+(?:of|for))[ \t]+)"
    rf"({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}})"
    r"(?=[ \t]+(?:(?i:ji|didi|sahab|behenji|bhai|babu)[ \t]+)?"
    r"\d{1,3}[ \t]*(?i:y|yr|yrs|years?)[ \t]*/[ \t]*(?i:m|f)\b)"
)
_TIMESTAMPED_AUTHOR = re.compile(
    rf"(?m)^([ \t]*\[\d{{1,4}}[/-]\d{{1,2}}[/-]\d{{1,4}},[ \t]*"
    rf"\d{{1,2}}:[0-5]\d(?:[ \t]*(?i:am|pm))?\][ \t]*)"
    rf"({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{1,3}})(?=[ \t]*:[ \t]+)"
)
_HINDI_SYMPTOM_SUBJECT = re.compile(
    rf"(?m)^([ \t]*)({_HINDI_NAME}(?:[ \t]+{_HINDI_NAME}){{1,3}})"
    r"(?=[ \t]+को[ \t]+\d{1,3}[ \t]+(?:दिन|घंटे|हफ्ते|सप्ताह)[ \t]+से)"
)
_ADDRESS_LINE = re.compile(r"(?im)^([ \t]*(?:पता|address|postal address|patient address)"
                           r"(?:[ \t]+\([a-z -]{1,24}\))?"
                           r"[ \t]*:[ \t]*)([^\r\n]+)")
_COARSE_ADDRESS_PART = re.compile(r"(?i)^(?:तहसील|जिला|ज़िला|district|tehsil|tahsil)(?=[ \t:=])")
_RELATIVE_SOURCE_NAME = re.compile(
    rf"(\b(?i:from)[ \t]+)({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}})"
    r"(?=['’]s[ \t]+[^\r\n()]{1,40}\([SDWsdw]/[Oo][ \t]+)"
)
_NOTE_SUBJECT = re.compile(
    rf"(?m)^([ \t]*(?:[01]\d|2[0-3]):[0-5]\d[ \t]+[-–][ \t]+)"
    rf"({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}})"
    r"(?=[ \t]+[-–][ \t]+(?i:K/C/O|C/O|BP|pulse)\b)"
)
_FAMILY_SUBJECT = re.compile(
    rf"(?m)^([ \t]*)({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{1,3}})"
    r"(?=[ \t]*,[ \t]*[SDWsdw]/[Oo]\b)"
)
_IDENTIFYING_HEADER = re.compile(
    rf"[A-Z]{{2,}}[A-Z0-9/-]*\d{{3,}}[ \t]+{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{1,3}}"
)
_LABELLED_PIN = re.compile(r"(?i)(\b(?:pin(?:[ \t]+code)?|post[ \t]*code)[ \t]*[:=]?[ \t]*)"
                           r"(\d{3})\d{3}(?!\d)")
_ADDRESS_PIN = re.compile(r"(?<!\d)(\d{3})\d{3}(?!\d)")
_CLINICAL_ADDRESS_PART = re.compile(
    r"(?i)^(?:bp|pulse|spo2|dose|diagnosis|बुखार|दवा|निदान)(?=\s|[:=])"
    r"|\b\d+(?:\.\d+)?[ \t]*(?:mg|mcg|ml|mmhg|mg/dl)\b"
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

    for pattern in (_EXPLICIT_NAME, _LAB_REPORT_NAME, _TIMESTAMPED_AUTHOR,
                    _HINDI_SYMPTOM_SUBJECT, _RELATIVE_SOURCE_NAME, _NOTE_SUBJECT, _FAMILY_SUBJECT):
        text = pattern.sub(replace_explicit, text)
    for pattern in (_HONORIFIC_NAME, _CLINICAL_POSSESSOR):
        text = pattern.sub(replace_honorific, text)
    def replace_address(match):
        nonlocal count
        parts = [part.strip() for part in re.split(r"[,;|]", match[2])]
        if any(_CLINICAL_ADDRESS_PART.search(part) for part in parts):
            return match[0]
        retained = [_ADDRESS_PIN.sub(r"\1***", part) for part in parts if _COARSE_ADDRESS_PART.match(part)]
        count += 1
        return match[1] + ", ".join(["[ADDRESS]", *retained])

    def replace_location(match):
        nonlocal count
        if match[3].strip() == "[ADDRESS]":
            return match[0]
        count += 1
        return match[1] + match[2] + "[ADDRESS]"

    text = _ADDRESS_LINE.sub(replace_address, text)
    text = _HINDI_LOCATION.sub(replace_location, text)
    text, pins = _LABELLED_PIN.subn(r"\1\2***", text)
    count += pins
    return text, count


def identifying_header(label: str) -> bool:
    return _IDENTIFYING_HEADER.fullmatch(label.strip()) is not None


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

"""Classify direct identifiers using their field labels."""

import re

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

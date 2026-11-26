"""Classify direct identifiers using their field labels."""

import re

_FIELDS = {
    "NAME": (
        "name", "patient name", "patients name", "full name", "first name", "last name",
        "given name", "family name", "naam", "नाम", "relative name", "guardian",
        "guardian name", "attendant name", "pita pati ka naam",
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

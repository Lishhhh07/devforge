"""Rewrite the local references and sensitive fields of FHIR bundles."""

from hashlib import sha256
import hmac
from uuid import UUID

from raksha.ingestion import Quarantine


def rewrite_bundle(bundle, key, clean_text, patient, shift):
    def opaque(value):
        return str(UUID(bytes=hmac.digest(key, value.encode("utf-8"), sha256)[:16], version=4))

    refs = {}
    entries = bundle.get("entry", [])
    if not isinstance(entries, list):
        raise Quarantine("invalid_fhir_bundle")
    for index, entry in enumerate(entries):
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(resource, dict) or not isinstance(resource.get("resourceType"), str):
            raise Quarantine("invalid_fhir_entry")
        if resource.get("contained"):
            raise Quarantine("unsupported_fhir_contained")
        target = opaque(f"entry|{index}")
        old_id = resource.get("id")
        aliases = [entry.get("fullUrl")]
        if isinstance(old_id, str):
            aliases.append(f"{resource['resourceType']}/{old_id}")
        for alias in aliases:
            if isinstance(alias, str):
                if alias in refs and refs[alias] != target:
                    raise Quarantine("ambiguous_fhir_reference")
                refs[alias] = target

    def visit(value, field=None):
        if isinstance(value, list):
            return [visit(item, field) for item in value]
        if isinstance(value, dict):
            result = {}
            for label, item in value.items():
                if label in {"identifier", "meta"}:
                    continue
                if label == "reference" and isinstance(item, str):
                    if item not in refs:
                        raise Quarantine("unresolved_fhir_reference")
                    result[label] = f"urn:uuid:{refs[item]}"
                elif label in {"data", "url"} and field == "attachment":
                    continue
                elif label == "div" and field == "text":
                    result[label] = clean_text(item) if isinstance(item, str) else item
                else:
                    result[label] = visit(item, label)
            return result
        if isinstance(value, str) and field not in {"system", "code", "url", "resourceType"}:
            return clean_text(shift(value))
        return value

    export = visit({label: value for label, value in bundle.items() if label != "entry"})
    if "id" in bundle:
        export["id"] = opaque("bundle")
    if bundle.get("type") == "document" and "identifier" in bundle:
        export["identifier"] = {"system": "urn:ietf:rfc:3986", "value": f"urn:uuid:{opaque('document')}"}
    if "entry" in bundle:
        export["entry"] = []
    for index, entry in enumerate(entries):
        resource = entry["resource"]
        if resource["resourceType"] == "Patient":
            resource = {label: value for label, value in resource.items()
                        if label not in {"name", "contact", "telecom", "text", "extension", "photo"}
                        and (label != "birthDate" or patient)}
            if isinstance(resource.get("address"), list):
                resource["address"] = [
                    {label: value for label, value in address.items()
                     if label in {"use", "type", "district", "state", "country"}}
                    for address in resource["address"] if isinstance(address, dict)
                ]
                resource["address"] = [address for address in resource["address"] if address]
        cleaned = visit({label: value for label, value in entry.items()
                         if label not in {"resource", "fullUrl"}})
        cleaned_resource = visit(resource)
        if patient and resource["resourceType"] == "Patient":
            cleaned_resource["identifier"] = [{"value": patient}]
        cleaned_resource["id"] = opaque(f"entry|{index}")
        cleaned["fullUrl"] = f"urn:uuid:{cleaned_resource['id']}"
        cleaned["resource"] = cleaned_resource
        export["entry"].append(cleaned)
    return export


def patient_evidence(bundle):
    entries = bundle.get("entry", [])
    if not isinstance(entries, list):
        return {}
    patients = [
        entry["resource"] for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)
        and entry["resource"].get("resourceType") == "Patient"
    ]
    if len(patients) != 1 or not isinstance(patients[0].get("identifier", []), list):
        return {}
    identifiers = patients[0].get("identifier", [])
    values = {item["value"] for item in identifiers if isinstance(item, dict)
              and isinstance(item.get("value"), str) and isinstance(item.get("system"), str)
              and item["system"].rstrip("/").casefold().endswith("/uhid")}
    return {"uhid": next(iter(values))} if len(values) == 1 else {}

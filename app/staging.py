"""Conservative visual contracts derived from explicit staging and cast descriptions.

These are shot constraints, never changes to the story's physical state ledger.
Ambiguous camera descriptions are left intact rather than guessing a subject.
"""
from __future__ import annotations

import re


def shoulder_subject(staging: str, people: dict[str, str]) -> str | None:
    if re.search(r"\b(?:not|never|avoid|instead of|rather than|don't|do not)\b", staging, re.I):
        return None
    matches = [name for name in people if re.search(
        rf"\bover\s+{re.escape(name)}['’]s\s+shoulder\b", staging, re.I)]
    return matches[0] if len(matches) == 1 else None


def camera_direction(staging: str, people: dict[str, str]) -> str:
    subject = shoulder_subject(staging, people)
    if not subject:
        return ''
    return (f"Camera placement: behind {subject} ({people[subject]}). Show the back of this character's "
            "head and a shoulder in the near foreground, partially cropped by the frame. "
            "This is the same individual, not an additional foreground person. "
            "The other subjects remain across from them as specified in the opening staging. "
            "Move the camera around the existing scene; retain the actors' physical positions.")


def material_facts(look: str, people: dict[str, str]) -> dict[str, str]:
    # Only an explicitly photographic mixed cast warrants a per-person material
    # contract. A cartoon human or an all-puppet film must retain its own medium.
    if (not re.search(r'\b(?:live[- ]action|photograph\w*)\b', look, re.I)
            or re.search(r'\b(?:cartoon|cel[- ]shad\w*|2d|hand[- ]drawn)\b', look, re.I)
            or re.search(r'\b(?:not|no|avoid)\s+(?:live[- ]action|photograph\w*)\b', look, re.I)):
        return {}
    puppets = {name for name, desc in people.items()
               if re.search(r'\b(?:cloth|felt|fabric)\s+puppet\b', desc, re.I)}
    humans = {name for name, desc in people.items()
              if re.search(r'\b(?:human|real person|living person)\b', desc, re.I)
              and name not in puppets}
    if not puppets or not humans:
        return {}
    return {name + ' · rendering material':
            ('A real photographed human with natural skin and hair' if name in humans else
             'A cloth puppet with visible fabric construction')
            for name in people if name in humans or name in puppets}


def visual_facts(staging: str, look: str, people: dict[str, str], phase: str) -> dict[str, str]:
    facts = material_facts(look, people)
    subject = shoulder_subject(staging, people) if phase == 'start' else None
    if subject:
        facts[subject + ' · camera orientation'] = (
            'Seen from behind in the near foreground, with the back of the head and a shoulder visible')
    return facts


def portrait_composition_prompt(opening: str, framing: str, scene: str, look: str,
                                people: dict[str, str]) -> str:
    """Compose a mixed cast from identity images without copying a stylized board.

    Caller supplies exactly two visible identities in image order. This route
    is only applicable to explicit photographic human/cloth-puppet scenes.
    """
    materials = material_facts(look, people)
    if len(people) != 2 or len(materials) != 2:
        raise ValueError('Mixed portrait composition requires two explicit material identities')
    identities = ' '.join(f'Picture {index} identifies {name} ({description}).'
                          for index, (name, description) in enumerate(people.items(), 1))
    return (f'Live-action photograph. {identities} Show these two individuals together once each. '
            f'Opening pose: {opening}. Framing: {framing}. Location: {scene}. '
            + ' '.join(f'{key.split(" · ")[0]}: {value}.' for key, value in materials.items()) +
            ' Preserve each reference character\'s face, hair, clothes and construction. '
            'Use the identities from the pictures, with poses from the opening direction. '
            f'Set and lighting direction: {look}. The set materials do not change the human into a figurine. '
            'Single film frame, no text or panels.')

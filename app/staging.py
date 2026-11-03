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
    other_people = ('The other subjects remain across from them as specified in the opening staging. '
                    if len(people) > 1 else '')
    return (f"View from behind {subject} ({people[subject]}). Show the back of this character's "
            "head and a shoulder in the near foreground, partially cropped by the frame. "
            "Their face is turned away and is not visible. "
            "This is the same individual, not an additional foreground person. "
            + other_people + "Keep the actors in their established physical positions.")


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


def shoulder_continuity(opening: str, ending: str, people: dict[str, str]) -> set[str]:
    """An opening angle alone places no constraint on later frames."""
    subject = shoulder_subject(opening, people)
    if not subject:
        return set()
    # Only extend the opening direction when the script explicitly holds it.
    hold = re.search(rf"\bover\s+{re.escape(subject)}['’]s\s+shoulder\s+"
                     r'\b(?:throughout(?: the shot)?|for the (?:whole|entire) shot)\b', opening, re.I)
    same_end = shoulder_subject(ending, people) == subject
    if hold and (not ending.strip() or same_end or not re.search(
            r'\b(?:turns?|faces? (?:the )?(?:camera|viewer)|profile|over .*shoulder)\b', ending, re.I)):
        return {'middle', 'end'}
    return {'end'} if same_end else set()


def back_view_description(description: str) -> str | None:
    """Keep wardrobe and other visible cues without asking a rear view to show facial traits."""
    facial = re.compile(r'\b(?:face|facial|eyes?|eyebrows?|eyelashes|nose|nostrils|mouth|lips?|teeth|'
                        r'cheeks?|chin|jaw|freckles?|dimples?|smiles?|beard|moustache|mustache)\b', re.I)
    visible_cues = re.compile(r'\b(?:hair|braids?|ponytail|hat|hood|coat|jacket|shirt|dress|scarf|'
                              r'cardigan|sweater|uniform|clothes|clothing|wardrobe|backpack|cape|wings?|tail)\b', re.I)
    parts = [part.strip(' .') for part in re.split(r'[,;.]', description or '') if part.strip(' .')]
    if any(facial.search(part) and visible_cues.search(part) for part in parts):
        return None  # A mixed clause cannot be separated without discarding visible direction.
    return ', '.join(part for part in parts if not facial.search(part))


def solo_rear_view(opening: str, people: dict[str, str], lead_name: str,
                   cast: str, identity: str) -> tuple[str, str] | None:
    """Use visible identity cues only when this is unambiguously the sole lead's rear view."""
    subject = shoulder_subject(opening, people)
    if len(people) != 1 or not subject or subject.casefold() != lead_name.casefold():
        return None
    visible_cast, visible_identity = back_view_description(cast), back_view_description(identity)
    if visible_cast is None or visible_identity is None:
        return None
    if not re.search(r'\b(?:hair|braids?|ponytail|hat|hood|coat|jacket|shirt|dress|scarf|'
                     r'cardigan|sweater|uniform|clothes|clothing|wardrobe|backpack|cape|wings?|tail)\b',
                     visible_cast + ' ' + visible_identity, re.I):
        return None
    return visible_cast, visible_identity


def solo_memory_rear_prompt(subject: str, cast: str, identity: str, opening: str,
                            action: str, scene: str, look: str, medium: str, continuity: str,
                            framing: str, camera: str) -> str:
    """The storyboard owns the pose; the second image supplies the remembered setting."""
    description = '. '.join(part.strip(' .') for part in (cast, identity) if part.strip(' .'))
    return (f'Picture 1 is the composition. Render it as {medium} in the setting of Picture 2. '
            f'{description}. Opening: {opening}. Scene action for context: {action}. '
            f'Framing: {framing}. ' + (f'Camera position: {camera}. ' if camera else '') +
            f'From directly behind {subject}, show the back of their head and shoulder in the foreground. '
            f'{subject} is the only person. Preserve the composition and camera angle from Picture 1. '
            f'Maintain the location, materials and lighting from Picture 2, while following the current staging. '
            f'Location: {scene}. Film look: {look}. '
            + (f'Continuity: {continuity}. ' if continuity.strip() else '')
            + 'Do not show their face or any other person. One finished frame, no text or borders.')


def visual_facts(staging: str, look: str, people: dict[str, str], phase: str, ending: str = '') -> dict[str, str]:
    facts = material_facts(look, people)
    subject = shoulder_subject(staging, people) if phase == 'start' or phase in shoulder_continuity(staging, ending, people) else None
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

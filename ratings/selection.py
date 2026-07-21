"""Отбор новых/изменённых релизов из листинга (агентство-независимо)."""

from __future__ import annotations

from .events import ChangeType, ReleaseStub
from .repository import RatingReleaseRepository


def select_changed(
    stubs: list[ReleaseStub], known: dict[str, str | None], early_stop: int
) -> tuple[list[ReleaseStub], dict[str, ChangeType]]:
    """Отбирает новые/изменённые стабы (ранняя остановка по серии известных)."""
    selected: list[ReleaseStub] = []
    change_by_uid: dict[str, ChangeType] = {}
    consecutive_known = 0

    for stub in stubs:
        modified_iso = stub.modified.isoformat() if stub.modified else None
        change = RatingReleaseRepository.classify(stub.uid, modified_iso, known)

        if change is None:
            consecutive_known += 1
            if early_stop and consecutive_known >= early_stop:
                break
            continue

        consecutive_known = 0
        selected.append(stub)
        change_by_uid[stub.uid] = change

    return selected, change_by_uid

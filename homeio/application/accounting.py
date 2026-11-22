"""Application use cases and the persistence port they require."""

from typing import Protocol
from homeio.domain.accounting import Movement


class Ledger(Protocol):
    def save_movement(self, movement: Movement, movement_id: int | None = None) -> int: ...
    def archive_movement(self, movement_id: int) -> None: ...


class Accounting:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def record(self, movement: Movement, movement_id: int | None = None) -> int:
        return self.ledger.save_movement(movement, movement_id)

    def archive(self, movement_id: int) -> None:
        self.ledger.archive_movement(movement_id)

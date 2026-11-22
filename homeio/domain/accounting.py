"""Business rules independent of HTTP and persistence."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


class ValidationError(ValueError):
    pass


def money_to_cents(value: str, *, allow_negative: bool = False) -> int:
    try:
        amount = Decimal(str(value).replace(",", "."))
        if not amount.is_finite() or abs(amount) > Decimal("999999999.99"):
            raise ValidationError("El importe está fuera del rango permitido.")
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise ValidationError("El importe debe tener como máximo dos decimales.")
        if not allow_negative and cents <= 0:
            raise ValidationError("El importe debe ser mayor que cero.")
        return int(cents)
    except InvalidOperation as exc:
        raise ValidationError("Introduce un importe válido.") from exc


@dataclass(frozen=True)
class Movement:
    description: str
    valid_date: str
    amount_cents: int
    movement_type: int
    category_id: int | None = None
    site_id: int | None = None

    def __post_init__(self) -> None:
        if not self.description.strip() or len(self.description) > 255:
            raise ValidationError("La descripción debe tener entre 1 y 255 caracteres.")
        try:
            parsed = date.fromisoformat(self.valid_date)
            if parsed.isoformat() != self.valid_date:
                raise ValueError
        except ValueError as exc:
            raise ValidationError("Introduce una fecha válida (AAAA-MM-DD).") from exc
        if self.movement_type not in (0, 1):
            raise ValidationError("El tipo debe ser gasto o ingreso.")
        if not 0 < self.amount_cents <= 99_999_999_999:
            raise ValidationError("Introduce un importe positivo dentro del rango permitido.")

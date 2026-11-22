import unittest
from homeio.domain.accounting import Movement, ValidationError, money_to_cents


class MoneyTests(unittest.TestCase):
    def test_exact_arithmetic(self):
        self.assertEqual(money_to_cents("0.10") + money_to_cents("0.20"), 30)
        self.assertEqual(money_to_cents("12,34"), 1234)

    def test_reject_invalid_money(self):
        for value in ("NaN", "Infinity", "-2", "0", "1.001", "1000000000", "abc", ""):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                money_to_cents(value)

    def test_movement_invariants(self):
        valid = dict(
            description="Electricity", valid_date="2026-11-01", amount_cents=200, movement_type=0
        )
        Movement(**valid)
        for field, value in [
            ("description", " "),
            ("valid_date", "2026-02-30"),
            ("movement_type", 2),
            ("amount_cents", -1),
        ]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Movement(**dict(valid, **{field: value}))

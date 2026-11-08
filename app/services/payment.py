"""Simulated payment gateway.

COD always succeeds. Online payment validates the card details and then
"charges" the card. No real money moves - this is a classroom simulation.

Test cards
----------
4242 4242 4242 4242  -> payment succeeds
4000 0000 0000 0002  -> card declined  (used to demonstrate payment failure)
"""
import re
from datetime import date

DECLINED_CARDS = {"4000000000000002"}


def _luhn_ok(number):
    total, flip = 0, False
    for ch in reversed(number):
        d = int(ch)
        if flip:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        flip = not flip
    return total % 10 == 0


def process_payment(method, amount, card_number="", expiry="", cvv=""):
    """Return (success: bool, message: str)."""
    if method == "COD":
        return True, "Cash on delivery selected."

    if method != "Online":
        return False, "Please choose a valid payment method."

    number = re.sub(r"[\s-]", "", card_number or "")
    if not number.isdigit() or not 13 <= len(number) <= 19 or not _luhn_ok(number):
        return False, "Payment failed: the card number is invalid."

    m = re.match(r"^(0[1-9]|1[0-2])\s*/\s*(\d{2})$", (expiry or "").strip())
    if not m:
        return False, "Payment failed: expiry date must be in MM/YY format."
    month, year = int(m.group(1)), 2000 + int(m.group(2))
    today = date.today()
    if (year, month) < (today.year, today.month):
        return False, "Payment failed: the card has expired."

    if not re.match(r"^\d{3,4}$", (cvv or "").strip()):
        return False, "Payment failed: CVV must be 3 or 4 digits."

    if number in DECLINED_CARDS:
        return False, "Payment failed: your card was declined by the bank."

    return True, "Payment successful."

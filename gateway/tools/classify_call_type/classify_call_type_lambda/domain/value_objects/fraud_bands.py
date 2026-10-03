"""Fraud-score bands, copied from transaction_fraud_detection.

The score is 0 to 100. Above FRAUD_ABOVE is FRAUD_SUSPECTED; above REVIEW_ABOVE
and up to FRAUD_ABOVE is UNRECOGNIZED_CHARGE_REVIEW. transaction_fraud_detection
keeps its own copy (tools never share code). Both tools' tests pin 50 and 30, so
a change to one shows up in the other's tests.
"""

from decimal import Decimal
from typing import Final

FRAUD_ABOVE: Final = Decimal("50")
REVIEW_ABOVE: Final = Decimal("30")

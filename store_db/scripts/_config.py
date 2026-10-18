"""Shared simulation constants used across generation scripts."""

import datetime

SEED = 42

SIM_START = datetime.date(2025, 1, 1)
SIM_END = datetime.date(2025, 12, 31)
SIM_MONTHS = [datetime.date(2025, m, 1) for m in range(1, 13)]

N_MERCHANTS = 10
N_CUSTOMERS = 150
TARGET_ORDERS = 300

CUSTOMER_COUNTRY_WEIGHTS = {
    "United States": 0.55,
    "Canada": 0.15,
    "United Kingdom": 0.10,
    "Germany": 0.08,
    "Australia": 0.07,
    "France": 0.05,
}

MERCHANT_COUNTRY_WEIGHTS = {
    "United States": 0.4,
    "China": 0.25,
    "Germany": 0.15,
    "South Korea": 0.1,
    "Taiwan": 0.1,
}

RETURN_REASONS_BY_CATEGORY = {
    "Electronics": ["defective", "not_as_described", "changed_mind", "wrong_item", "better_price_found"],
    "Cameras & Optics": ["defective", "not_as_described", "changed_mind", "wrong_item"],
    "Apparel & Accessories": ["wrong_size", "not_as_described", "changed_mind"],
    "Sporting Goods": ["not_as_described", "changed_mind", "defective"],
}
DEFAULT_RETURN_REASON_WEIGHTS = {
    "Electronics": [0.40, 0.25, 0.20, 0.10, 0.05],
    "Cameras & Optics": [0.35, 0.30, 0.25, 0.10],
    "Apparel & Accessories": [0.45, 0.30, 0.25],
    "Sporting Goods": [0.30, 0.40, 0.30],
}

CARRIERS = ["UPS", "FedEx", "USPS", "DHL"]
PAYMENT_METHODS = ["credit_card", "paypal", "bank_transfer"]
PAYMENT_METHOD_WEIGHTS = [0.55, 0.30, 0.15]

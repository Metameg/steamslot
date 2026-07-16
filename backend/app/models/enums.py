import enum


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class LedgerEntryType(str, enum.Enum):
    deposit = "deposit"
    pack_purchase = "pack_purchase"
    buyback_credit = "buyback_credit"
    withdrawal = "withdrawal"
    refund = "refund"
    admin_adjustment = "admin_adjustment"


class PackStatus(str, enum.Enum):
    unopened = "unopened"
    opened = "opened"


class PullStatus(str, enum.Enum):
    vaulted = "vaulted"
    bought_back = "bought_back"
    redeem_requested = "redeem_requested"
    redeemed = "redeemed"


class RedemptionStatus(str, enum.Enum):
    pending = "pending"
    fulfilled = "fulfilled"
    cancelled = "cancelled"


class WithdrawalStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"


class StripeEventStatus(str, enum.Enum):
    received = "received"
    processed = "processed"
    failed = "failed"

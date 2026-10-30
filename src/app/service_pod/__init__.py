"""Service POD: the five governed finance workflows of the V1.1 deck (AR collections, bank to
invoice reconciliation, FP&A trends, treasury forecast, financial reporting).

QuickBooks is read only here: the module works on immutable source snapshots, and anything
that must be booked becomes a manual posting task that a Finance Admin performs outside the
application and proves with a fresh snapshot.
"""

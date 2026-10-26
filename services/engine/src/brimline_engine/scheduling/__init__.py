"""Production scheduling (M3): the task model, two baselines, and the CP-SAT scheduler.

Everything here works on an in-memory Instance and returns a Schedule; nothing touches the
database. The independent checker (M4) re-validates schedules without importing this package.
"""

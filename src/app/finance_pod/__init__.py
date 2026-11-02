"""Finance POD: the GIA AP (Procure-to-Pay) and AR (Order-to-Cash) agents, built on the
Service POD's case engine.

Every L4 task and L5 step of the requirement's future-state slides is a declared step of a
workflow (requirements/ holds the requirement as data, and a test fails when a phase that is
marked implemented misses any of it). An agent prepares, a person holding the capacity
decides, and segregation of duties holds even for a Finance Admin.

    capacities.py   the roles the requirement names ("Who")
    models.py       capacity assignments
    access.py       who gets into the Finance POD, and with which capacities
    requirements/   the requirement transcribed (L3 / L4 / L5, rules, measures)
    flows/          one package per workflow (registered like the Service POD's)
    router.py       /api/v1/finance/...
"""

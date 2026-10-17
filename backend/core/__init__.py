"""Pure matching core (architecture S2-S6): normalize, block, features, score, band.

Every function here is free of database, network, clock and unseeded randomness so the
API, the FrontDesk gate and the evaluation executors compute identical results from the
same inputs. This package never imports ``backend.frontdesk``.
"""

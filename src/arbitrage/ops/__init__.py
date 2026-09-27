"""Operating core: the deterministic services that hold money, permissions and transaction state.

Agents (and the scanner in `arbitrage`) propose; these services decide and record.  Everything here
is either *simulated* or *live* and says which on every row it writes.  Live actions are refused
until the owner's mandate (mandate.toml) has no pending field.
"""

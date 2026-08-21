"""
Relationship verdicts — the signal a verification run publishes.

A relation is not simply present or absent. Four states matter and get confused
if collapsed into a boolean:

  CONFIRMED     the path resolved on real resources and the values pointed at
                resources that exist. The relation is real and exercised here.

  PARTIAL       the path resolved on some source resources but not all, or some
                targets resolved and others dangled. Normal and expected - not
                every instance is in a VPC, not every volume is attached - so
                this is a healthy state, not a defect.

  ABSENT        the path is structurally valid but was never populated on any
                observed resource. The relation is probably fine; this account
                just does not exercise it. MUST NOT be treated as refutation:
                deleting it would silently lose a correct relation the moment an
                account happens to have no Lambdas in a VPC.

  REFUTED       values were found but they fail the type conditions - wrong
                id_prefix, or an ARN naming a different service. This is the
                only verdict that says the relation itself is wrong.

  UNVERIFIABLE  the target type was not collected, so referential integrity
                could not be tested. Says nothing about the relation.

  PENDING       never run.

The distinction that does the real work is ABSENT vs REFUTED. An unexercised
relation and a wrong relation look identical if you only count resolved edges.
Only a condition violation refutes.
"""

from collections import namedtuple

CONFIRMED = 'confirmed'
PARTIAL = 'partial'
ABSENT = 'absent'
REFUTED = 'refuted'
UNVERIFIABLE = 'unverifiable'
PENDING = 'pending'

ORDER = [CONFIRMED, PARTIAL, ABSENT, UNVERIFIABLE, REFUTED, PENDING]

# Columns a verification run writes back onto a relation row.
SIGNAL_FIELDS = [
    'verdict', 'observed_sources', 'observed_hits', 'hit_rate',
    'resolved_targets', 'dangling_targets', 'condition_violations',
    'verdict_detail', 'verified_at',
]

Observation = namedtuple(
    'Observation',
    'sources hits values resolved dangling violations target_collected')


def blank_signals():
    """Signal columns for a relation that has never been verified."""
    return {
        'verdict': PENDING, 'observed_sources': '', 'observed_hits': '',
        'hit_rate': '', 'resolved_targets': '', 'dangling_targets': '',
        'condition_violations': '', 'verdict_detail': '', 'verified_at': '',
    }


def classify(obs, refute_threshold=0.5):
    """
    Turn one relation's observations into a verdict plus a human-readable reason.

    `refute_threshold` is the share of found values that must violate the type
    conditions before the relation is called wrong. It is not zero because a
    single odd value - a cross-account ARN, a resource mid-deletion - should not
    condemn an otherwise sound path.
    """
    if obs.sources == 0:
        return ABSENT, 'no source resources of this type were collected'

    if obs.hits == 0:
        return ABSENT, f'path never populated across {obs.sources} resource(s)'

    if obs.values and obs.violations / obs.values >= refute_threshold:
        return REFUTED, (f'{obs.violations}/{obs.values} values failed the type '
                         f'condition (wrong id_prefix or ARN service)')

    if not obs.target_collected:
        return UNVERIFIABLE, ('target type was not collected, so referential '
                              'integrity is untested')

    if obs.dangling and obs.resolved == 0:
        return REFUTED, (f'all {obs.dangling} value(s) resolved to nothing in the '
                         f'target inventory')

    if obs.hits < obs.sources or obs.dangling:
        return PARTIAL, (f'{obs.hits}/{obs.sources} resources populated the path; '
                         f'{obs.resolved} target(s) resolved, {obs.dangling} dangled')

    return CONFIRMED, (f'all {obs.sources} resource(s) populated the path and '
                       f'{obs.resolved} target(s) resolved')


def to_signals(obs, verdict, detail, verified_at):
    """Render an observation into the writable signal columns."""
    return {
        'verdict': verdict,
        'observed_sources': obs.sources,
        'observed_hits': obs.hits,
        'hit_rate': f'{obs.hits / obs.sources:.2f}' if obs.sources else '',
        'resolved_targets': obs.resolved,
        'dangling_targets': obs.dangling,
        'condition_violations': obs.violations,
        'verdict_detail': detail,
        'verified_at': verified_at,
    }


def merge_verdicts(verdicts):
    """
    Combine verdicts for the same relation seen across accounts or regions.

    Deliberately optimistic on evidence and pessimistic on refutation: one
    account confirming a relation is proof it exists, while ABSENT elsewhere
    only means unexercised there. REFUTED still wins over everything, because a
    type-condition violation is a property of the path, not of the account.
    """
    seen = set(verdicts)
    if REFUTED in seen:
        return REFUTED
    for candidate in (CONFIRMED, PARTIAL, UNVERIFIABLE, ABSENT):
        if candidate in seen:
            return candidate
    return PENDING


def promotes_confidence(verdict):
    """Whether a verdict justifies promoting a mined guess to trusted."""
    return verdict in (CONFIRMED, PARTIAL)


def demotes(verdict):
    """Whether a verdict should stop a relation being used to draw edges."""
    return verdict == REFUTED

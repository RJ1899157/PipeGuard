"""Evaluate producer-declared step inventories without treating partial delivery as complete."""


def missing_metadata(payloads):
    """Input reports must belong to one monitored external execution and attempt."""
    gaps=set()
    inventories=[]
    steps={}
    for p in payloads:
        inventory={(s['namespace'],s['name']) for s in p.get('expected_steps',[])}
        if not inventory:
            gaps.add('lineage_inventory_unknown')
        else:
            inventories.append(inventory)
        event=p['event'];key=(event['job']['namespace'],event['job']['name'])
        steps.setdefault(key,[]).append(p)

    for values in steps.values():
        latest = values[-1]
        if latest['coverage'] != 'complete':gaps.update(latest['missing_metadata'])
    if inventories:
        expected=set().union(*inventories)
        if any(i!=inventories[0] for i in inventories):gaps.add('lineage_inventory_changed')
        if expected-set(steps):gaps.add('missing_expected_steps')
        if set(steps)-expected:gaps.add('unexpected_step')
        for key in expected & set(steps):
            values=steps[key]
            outcomes={p['event']['eventType'] for p in values} & {'COMPLETE','FAIL','ABORT'}
            if not outcomes:gaps.add('missing_terminal_lineage')
            if len(outcomes)>1:gaps.add('contradictory_run_outcomes')
    if not payloads:gaps.add('no_lineage_observed')
    return gaps

"""Choose thresholds on development tasks; protect held-out tasks."""
def choose(dev_scores,thresholds=(.7,.8,.85,.9)):
    options=[(t,dev_scores[t]) for t in thresholds if t in dev_scores]
    if not options:raise ValueError("Missing development evaluations")
    return min(options,key=lambda p:(p[1].get("false_verified_rate",1.0),
                                      -p[1].get("resolved",0),p[0]))

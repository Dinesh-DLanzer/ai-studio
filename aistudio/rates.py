"""E5: price per second lookup.  Standard library only.

Contract (tests in tests/test_rates.py):
  rate_for(rates: dict, model: str, res: str, secs: int | None = None, audio: bool = False) -> float
      `rates` looks like {"models": {"<model>": {"<res>": <rate>}}}.  A rate is one of:
        a number                                      -> that number
        {"audio": x, "no_audio": y}                   -> x if audio else y
        [{"up_to": 8, "rate": 0.3}, {"rate": 0.2}]   -> duration tiers: the first tier with secs <= up_to
                                                        (a tier without "up_to" matches anything)
      Raises KeyError if the model or resolution is missing, ValueError if tiers need `secs` and it is None or no
      tier matches.
  clip_cost(rates: dict, model: str, res: str, secs: int, audio: bool = False) -> float
      rate_for(...) * secs, rounded to 6 decimals.
"""


def rate_for(rates, model, res, secs=None, audio=False):
    try:
        rate_def = rates["models"][model][res]
    except KeyError:
        raise KeyError

    if isinstance(rate_def, (int, float)):
        return rate_def

    if isinstance(rate_def, dict):
        if audio:
            return rate_def["audio"]
        return rate_def["no_audio"]

    if isinstance(rate_def, list):
        if secs is None:
            raise ValueError
        for tier in rate_def:
            if "up_to" in tier:
                if secs <= tier["up_to"]:
                    return tier["rate"]
            else:
                return tier["rate"]
        raise ValueError

    raise ValueError


def clip_cost(rates, model, res, secs, audio=False):
    rate = rate_for(rates, model, res, secs, audio)
    return round(rate * secs, 6)
